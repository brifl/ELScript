from __future__ import annotations

from dataclasses import replace

import pytest

from elscript.compiler import compile_document
from elscript.config import EffectiveConfig, resolve_config
from elscript.domain import CompiledScript
from elscript.errors import CapabilityError, UnsupportedModelFeatureError
from elscript.loading import load_document
from elscript.planner import RenderPlan, plan_render
from elscript.providers.base import ProviderFeature, RequestKind
from elscript.providers.elevenlabs_prompt import (
    ELEVEN_V3_MODEL,
    TRANSLATION_VERSION,
    ElevenLabsOperation,
    ElevenLabsTranslation,
    build_elevenlabs_request,
    elevenlabs_capabilities,
    prepare_elevenlabs,
)
from elscript.schema import ELScriptDocument
from elscript.validation import validate_document


def _pipeline(
    *,
    script: list[dict[str, object]],
    render: dict[str, object] | None = None,
    pronunciation: dict[str, object] | None = None,
    characters: dict[str, object] | None = None,
    chunking_max: int = 1_800,
    output_mode: str = "single",
) -> tuple[
    ELScriptDocument,
    CompiledScript,
    EffectiveConfig,
    ElevenLabsTranslation,
    RenderPlan,
]:
    document = validate_document(
        load_document(
            document={
                "elscript": "1.0",
                "render": render or {},
                "pronunciation": pronunciation or {},
                "characters": characters
                or {
                    "MARA": {"voice_id": "mara"},
                    "ORION": {"voice_id": "orion"},
                },
                "scenes": [{"id": "scene", "script": script}],
                "export": {"mode": output_mode},
            }
        )
    )
    config = resolve_config(
        document,
        process_env={},
        options={"chunking": {"max_chars": chunking_max}},
    )
    compiled = compile_document(document, config)
    translation = prepare_elevenlabs(compiled, document.pronunciation)
    plan = plan_render(
        compiled,
        config,
        elevenlabs_capabilities(),
        dictionaries=translation.dictionary_locators,
        prepared_segments=translation.prepared_segments,
    )
    return document, compiled, config, translation, plan


def test_v3_semantics_cues_and_tags_have_one_deterministic_order() -> None:
    _, _, _, translation, plan = _pipeline(
        script=[
            {
                "MARA": {
                    "with": {
                        "emotion": "frightened",
                        "intensity": 0.75,
                        "energy": 0.8,
                        "pace": "slow",
                        "volume": "whisper",
                        "delivery": ["trembling", "restrained"],
                        "accent": "French",
                    },
                    "cue": ["exhales", "nervous laugh"],
                    "tags": ["raw-first", "raw-second"],
                    "say": "Don't move.",
                }
            }
        ]
    )

    prompt = plan.requests[0].parts[0].text

    assert prompt == (
        "[frightened] [intense] [high energy] [slowly] [whispers] "
        "[trembling] [restrained] [strong French accent] [exhales] "
        "[nervous laugh] [raw-first] [raw-second] Don't move."
    )
    assert [warning.code for warning in translation.warnings] == [
        "ELEVENLABS_INTENSITY_APPROXIMATED",
        "ELEVENLABS_ENERGY_APPROXIMATED",
        "ELEVENLABS_SEMANTIC_TAG_EXPERIMENTAL",
    ]
    assert plan.requests[0].parts[0].translation_version == TRANSLATION_VERSION


def test_prepared_prompt_is_split_after_translation_and_within_provider_limit() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "12345 New York city"}],
        render={"mode": "speech"},
        pronunciation={"terms": {"New York": {"say_as": "NYC"}}},
        chunking_max=10,
    )

    texts = [part.text or "" for request in plan.requests for part in request.parts]

    assert "".join(texts) == "12345 NYC city"
    assert all(request.character_count <= 10 for request in plan.requests)
    assert all(
        part.translation_version == TRANSLATION_VERSION
        for request in plan.requests
        for part in request.parts
    )


def test_expressive_prefix_is_repeated_intact_when_text_is_split() -> None:
    _, _, _, _, plan = _pipeline(
        script=[
            {
                "MARA": {
                    "with": {"emotion": "afraid"},
                    "say": "alpha beta gamma",
                }
            }
        ],
        render={"mode": "speech"},
        chunking_max=14,
    )

    prompts = [request.parts[0].text or "" for request in plan.requests]

    assert len(prompts) > 1
    assert all(prompt.startswith("[afraid] ") for prompt in prompts)
    assert "".join(prompt.removeprefix("[afraid] ") for prompt in prompts) == (
        "alpha beta gamma"
    )
    assert all(request.character_count <= 14 for request in plan.requests)


def test_raw_voice_settings_make_auto_mode_fall_back_to_speech() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}, {"ORION": "Two"}],
        render={"api": {"voice_settings": {"stability": 0.5, "speed": 0.9}}},
    )

    assert [request.kind for request in plan.requests] == [
        RequestKind.SPEECH,
        RequestKind.SPEECH,
    ]
    materialized = build_elevenlabs_request(plan.requests[0], elevenlabs_capabilities())
    assert materialized.body["voice_settings"] == {"stability": 0.5, "speed": 0.9}


def test_dialogue_only_options_can_select_dialogue_for_one_speaker_in_auto_mode() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}],
        render={"api": {"settings": {"stability": "natural"}}},
    )

    assert [request.kind for request in plan.requests] == [RequestKind.DIALOGUE]
    materialized = build_elevenlabs_request(plan.requests[0], elevenlabs_capabilities())
    assert materialized.body["settings"] == {"stability": "natural"}


def test_raw_options_are_validated_for_selected_endpoint_and_value_ranges() -> None:
    with pytest.raises(UnsupportedModelFeatureError, match="voice_settings"):
        _pipeline(
            script=[{"MARA": "One"}, {"ORION": "Two"}],
            render={
                "mode": "dialogue",
                "api": {"voice_settings": {"stability": 0.5}},
            },
        )

    _, _, _, _, invalid_plan = _pipeline(
        script=[{"MARA": "One"}],
        render={"mode": "speech", "api": {"voice_settings": {"speed": 2.0}}},
    )
    with pytest.raises(CapabilityError, match="between 0.7 and 1.2"):
        build_elevenlabs_request(invalid_plan.requests[0], elevenlabs_capabilities())


def test_conflicting_continuity_inputs_cannot_be_silently_ignored() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}],
        render={
            "mode": "speech",
            "api": {
                "previous_text": "Before",
                "previous_request_ids": ["request-before"],
            },
        },
    )

    with pytest.raises(CapabilityError, match="mutually exclusive"):
        build_elevenlabs_request(plan.requests[0], elevenlabs_capabilities())


def test_dialogue_settings_and_core_options_materialize_without_aliasing() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}, {"ORION": "Two"}],
        render={
            "mode": "dialogue",
            "timestamps": True,
            "seed": 42,
            "api": {"settings": {"stability": "natural"}},
        },
    )

    request = build_elevenlabs_request(plan.requests[0], elevenlabs_capabilities())
    identity = request.fingerprint_inputs()

    assert request.operation is ElevenLabsOperation.CREATE_DIALOGUE_WITH_TIMESTAMPS
    assert request.voice_id is None
    assert request.body["settings"] == {"stability": "natural"}
    assert request.body["seed"] == 42
    assert request.query == {"output_format": "mp3_44100_128", "enable_logging": True}
    assert request.warnings[0].code == "ELEVENLABS_SEED_BEST_EFFORT"
    assert identity["translation_version"] == TRANSLATION_VERSION
    assert identity["body"]["inputs"] == [
        {"text": "One", "voice_id": "mara"},
        {"text": "Two", "voice_id": "orion"},
    ]


@pytest.mark.parametrize(
    ("streaming", "timestamps", "operation"),
    [
        (False, False, ElevenLabsOperation.CREATE_SPEECH),
        (False, True, ElevenLabsOperation.CREATE_SPEECH_WITH_TIMESTAMPS),
        (True, False, ElevenLabsOperation.STREAM_SPEECH),
        (True, True, ElevenLabsOperation.STREAM_SPEECH_WITH_TIMESTAMPS),
    ],
)
def test_speech_operation_selection_is_explicit(
    streaming: bool,
    timestamps: bool,
    operation: ElevenLabsOperation,
) -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}],
        render={"mode": "speech", "timestamps": timestamps},
    )
    planned = replace(plan.requests[0], streaming=streaming)

    request = build_elevenlabs_request(planned, elevenlabs_capabilities())

    assert request.operation is operation
    assert request.voice_id == "mara"


def test_missing_translated_feature_fails_before_request_generation() -> None:
    document, compiled, config, translation, _ = _pipeline(
        script=[{"MARA": {"with": {"emotion": "afraid"}, "say": "One"}}]
    )
    capabilities = elevenlabs_capabilities()
    assert capabilities.speech is not None
    capabilities = replace(
        capabilities,
        speech=replace(
            capabilities.speech,
            features=capabilities.speech.features - {ProviderFeature.AUDIO_TAGS},
        ),
        dialogue=None,
    )

    with pytest.raises(UnsupportedModelFeatureError, match="audio_tags"):
        plan_render(
            compiled,
            config,
            capabilities,
            dictionaries=translation.dictionary_locators,
            prepared_segments=translation.prepared_segments,
        )
    assert document.elscript == "1.0"


def test_non_v3_expressive_intent_and_malformed_tags_are_rejected() -> None:
    with pytest.raises(UnsupportedModelFeatureError, match="cannot honor"):
        _pipeline(
            script=[{"MARA": {"with": {"emotion": "afraid"}, "say": "One"}}],
            characters={"MARA": {"voice_id": "mara", "model": "other-model"}},
        )

    with pytest.raises(CapabilityError, match="invalid tag syntax"):
        _pipeline(script=[{"MARA": {"tags": ["bad]tag"], "say": "One"}}])


def test_dictionary_locators_preserve_order_and_use_api_field_names() -> None:
    _, _, _, translation, plan = _pipeline(
        script=[{"MARA": "One"}],
        render={"mode": "speech"},
        pronunciation={
            "dictionaries": [
                {"id": "first", "version_id": "v1"},
                {"id": "second", "version_id": "v2"},
                {"id": "first", "version_id": "v1"},
            ]
        },
    )

    request = build_elevenlabs_request(plan.requests[0], elevenlabs_capabilities())

    assert [(item.id, item.version_id) for item in translation.dictionary_locators] == [
        ("first", "v1"),
        ("second", "v2"),
    ]
    assert request.body["pronunciation_dictionary_locators"] == (
        {"pronunciation_dictionary_id": "first", "version_id": "v1"},
        {"pronunciation_dictionary_id": "second", "version_id": "v2"},
    )


def test_conflicting_or_excess_dictionary_locators_fail() -> None:
    with pytest.raises(CapabilityError, match="conflicting versions"):
        _pipeline(
            script=[{"MARA": "One"}],
            pronunciation={
                "dictionaries": [
                    {"id": "same", "version_id": "v1"},
                    {"id": "same", "version_id": "v2"},
                ]
            },
        )

    with pytest.raises(CapabilityError, match="at most 3"):
        _pipeline(
            script=[{"MARA": "One"}],
            pronunciation={
                "dictionaries": [
                    {"id": f"dictionary-{index}", "version_id": "v1"}
                    for index in range(4)
                ]
            },
        )


def test_seed_range_is_validated_before_transport() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}],
        render={"mode": "speech", "seed": -1},
    )

    with pytest.raises(CapabilityError, match="seed must be an integer"):
        build_elevenlabs_request(plan.requests[0], elevenlabs_capabilities())


def test_language_normalization_rejects_known_unsupported_language() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}],
        render={"mode": "speech", "language_text_normalization": True},
        characters={"MARA": {"voice_id": "mara", "language": "en"}},
    )

    with pytest.raises(UnsupportedModelFeatureError, match="only for Japanese"):
        build_elevenlabs_request(plan.requests[0], elevenlabs_capabilities())


def test_native_ipa_is_never_split_into_malformed_provider_text() -> None:
    with pytest.raises(CapabilityError, match="indivisible provider token"):
        _pipeline(
            script=[{"MARA": "Term"}],
            render={"mode": "speech"},
            pronunciation={"terms": {"Term": {"ipa": "abcdefghijklmnop"}}},
            chunking_max=10,
        )


def test_request_builder_rejects_nested_credentials_at_its_boundary() -> None:
    _, _, _, _, plan = _pipeline(
        script=[{"MARA": "One"}],
        render={"mode": "dialogue", "api": {"settings": {"stability": "natural"}}},
    )
    unsafe = replace(
        plan.requests[0],
        provider_options={"settings": {"api_key": "must-not-escape"}},
    )

    with pytest.raises(CapabilityError, match="Credentials are not valid") as caught:
        build_elevenlabs_request(unsafe, elevenlabs_capabilities())
    assert "must-not-escape" not in str(caught.value)


def test_capability_snapshot_matches_current_dialogue_constraints() -> None:
    capabilities = elevenlabs_capabilities()

    assert capabilities.capability_version == "elevenlabs-2026-08-14"
    assert capabilities.dialogue is not None
    assert capabilities.dialogue.supported_models == {ELEVEN_V3_MODEL}
    assert capabilities.dialogue.max_unique_voices == 10
    assert capabilities.dialogue.recommended_request_chars == 2_000
    assert capabilities.dialogue.max_pronunciation_dictionaries == 3
