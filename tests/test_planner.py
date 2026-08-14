from __future__ import annotations

from dataclasses import replace

from elscript.compiler import compile_document
from elscript.config import EffectiveConfig, resolve_config
from elscript.domain import CompiledScript, MarkerEvent, PauseEvent
from elscript.loading import load_document
from elscript.planner import plan_render
from elscript.providers.base import EndpointCapabilities, ProviderFeature, RequestKind
from elscript.providers.fake import fake_capabilities
from elscript.validation import validate_document


def _compile(
    scenes: list[dict[str, object]],
    *,
    characters: dict[str, object] | None = None,
    render: dict[str, object] | None = None,
    output_mode: str = "single",
    chunking_max: int = 1_800,
) -> tuple[CompiledScript, EffectiveConfig]:
    document = validate_document(
        load_document(
            document={
                "elscript": "1.0",
                "render": render or {},
                "characters": characters
                or {
                    "MARA": {"voice_id": "mara"},
                    "ORION": {"voice_id": "orion"},
                },
                "scenes": scenes,
                "export": {"mode": output_mode},
            }
        )
    )
    config = resolve_config(
        document,
        process_env={},
        options={"provider": "fake", "chunking": {"max_chars": chunking_max}},
    )
    return compile_document(document, config), config


def test_auto_groups_dialogue_and_honors_ordering_boundaries() -> None:
    compiled, config = _compile(
        [
            {
                "id": "one",
                "script": [
                    {"MARA": "First"},
                    {"ORION": "Second"},
                    {"marker": "beat"},
                    {"MARA": "Third"},
                    {"pause": 0.5},
                    {"ORION": "Fourth"},
                ],
            },
            {"id": "two", "script": [{"MARA": "Fifth"}]},
        ]
    )

    plan = plan_render(compiled, config, fake_capabilities())

    assert [request.kind for request in plan.requests] == [
        RequestKind.DIALOGUE,
        RequestKind.SPEECH,
        RequestKind.SPEECH,
        RequestKind.SPEECH,
    ]
    assert [part.logical_id for part in plan.requests[0].parts] == [
        compiled.segments[0].id,
        compiled.segments[1].id,
    ]
    assert any(isinstance(event, MarkerEvent) for event in plan.timeline)
    assert any(isinstance(event, PauseEvent) for event in plan.timeline)
    assert all(
        len({part.segment.scene_id for part in request.parts}) == 1
        for request in plan.requests
    )


def test_incompatible_model_and_provider_options_split_requests() -> None:
    compiled, config = _compile(
        [
            {
                "id": "scene",
                "script": [
                    {"MARA": {"say": "One", "api": {"voice_settings": {"speed": 1.0}}}},
                    {"ORION": {"say": "Two", "api": {"voice_settings": {"speed": 0.8}}}},
                    {"THIRD": "Three"},
                ],
            }
        ],
        characters={
            "MARA": {"voice_id": "mara"},
            "ORION": {"voice_id": "orion"},
            "THIRD": {"voice_id": "third", "model": "other-model"},
        },
    )

    plan = plan_render(compiled, config, fake_capabilities())

    assert len(plan.requests) == 3
    assert all(request.kind is RequestKind.SPEECH for request in plan.requests)
    assert [request.model for request in plan.requests] == [
        "eleven_v3",
        "eleven_v3",
        "other-model",
    ]


def test_dialogue_batches_respect_character_and_unique_voice_limits() -> None:
    compiled, config = _compile(
        [
            {
                "id": "scene",
                "script": [
                    {"ONE": "aaaa"},
                    {"TWO": "bbbb"},
                    {"THREE": "cccc"},
                    {"ONE": "dddd"},
                ],
            }
        ],
        characters={
            "ONE": {"voice_id": "one"},
            "TWO": {"voice_id": "two"},
            "THREE": {"voice_id": "three"},
        },
        render={"mode": "dialogue"},
        chunking_max=10,
    )
    capabilities = fake_capabilities(request_chars=100)
    assert capabilities.dialogue is not None
    capabilities = replace(
        capabilities,
        dialogue=replace(capabilities.dialogue, max_unique_voices=2),
    )

    plan = plan_render(compiled, config, capabilities)

    assert [request.character_count for request in plan.requests] == [8, 8]
    voice_counts = [
        len({part.segment.voice_id for part in request.parts}) for request in plan.requests
    ]
    assert voice_counts == [
        2,
        2,
    ]
    assert all(request.kind is RequestKind.DIALOGUE for request in plan.requests)


def test_long_logical_segment_splits_losslessly_into_ordered_request_parts() -> None:
    text = "alpha beta gamma delta"
    compiled, config = _compile(
        [{"id": "scene", "script": [{"MARA": {"id": "long.line", "say": text}}]}],
        render={"mode": "speech"},
        chunking_max=10,
    )

    plan = plan_render(compiled, config, fake_capabilities(request_chars=100))
    parts = [request.parts[0] for request in plan.requests]

    assert "".join(part.text or "" for part in parts) == text
    assert {part.logical_id for part in parts} == {"long.line"}
    assert [part.part_index for part in parts] == list(range(1, len(parts) + 1))
    assert {part.part_count for part in parts} == {len(parts)}
    assert all(request.character_count <= 10 for request in plan.requests)


def test_auto_uses_speech_when_segment_output_cannot_extract_dialogue() -> None:
    compiled, config = _compile(
        [{"id": "scene", "script": [{"MARA": "One"}, {"ORION": "Two"}]}],
        output_mode="segment",
    )
    capabilities = fake_capabilities()
    assert capabilities.dialogue is not None
    dialogue_features = capabilities.dialogue.features - {
        ProviderFeature.TIMESTAMPS,
        ProviderFeature.SPEAKER_SEGMENTS,
    }
    capabilities = replace(
        capabilities,
        dialogue=replace(capabilities.dialogue, features=dialogue_features),
    )

    plan = plan_render(compiled, config, capabilities)

    assert [request.kind for request in plan.requests] == [
        RequestKind.SPEECH,
        RequestKind.SPEECH,
    ]


def test_identical_inputs_produce_structurally_identical_plans() -> None:
    compiled, config = _compile(
        [{"id": "scene", "script": [{"MARA": "One"}, {"ORION": "Two"}]}]
    )

    first = plan_render(compiled, config, fake_capabilities())
    second = plan_render(compiled, config, fake_capabilities())

    assert first == second
    assert [request.id for request in first.requests] == ["request.0001"]


def test_auto_dialogue_counts_speakers_separately_from_unique_voices() -> None:
    compiled, config = _compile(
        [{"id": "scene", "script": [{"MARA": "One"}, {"ORION": "Two"}]}],
        characters={
            "MARA": {"voice_id": "shared"},
            "ORION": {"voice_id": "shared"},
        },
    )

    plan = plan_render(compiled, config, fake_capabilities())

    assert plan.requests[0].kind is RequestKind.DIALOGUE
    assert len({part.segment.speaker for part in plan.requests[0].parts}) == 2
    assert len({part.segment.voice_id for part in plan.requests[0].parts}) == 1


def test_direction_characters_are_counted_for_request_limits() -> None:
    compiled, config = _compile(
        [
            {
                "id": "scene",
                "script": [{"MARA": {"cue": "sighs", "say": "abcdefghij"}}],
            }
        ],
        render={"mode": "speech"},
        chunking_max=12,
    )

    plan = plan_render(compiled, config, fake_capabilities(request_chars=100))

    assert len(plan.requests) > 1
    assert all(request.character_count <= 12 for request in plan.requests)


def test_dialogue_plan_requests_timestamps_needed_for_segment_output() -> None:
    compiled, config = _compile(
        [{"id": "scene", "script": [{"MARA": "One"}, {"ORION": "Two"}]}],
        render={"mode": "dialogue", "timestamps": False},
        output_mode="segment",
    )

    plan = plan_render(compiled, config, fake_capabilities())

    assert len(plan.requests) == 1
    assert plan.requests[0].kind is RequestKind.DIALOGUE
    assert plan.requests[0].timestamps is True


def test_capability_constraints_are_endpoint_specific() -> None:
    speech = EndpointCapabilities(
        features=frozenset({ProviderFeature.STREAMING}),
        supported_models=frozenset({"speech-model"}),
    )
    dialogue = EndpointCapabilities(
        features=frozenset({ProviderFeature.TIMESTAMPS}),
        supported_models=frozenset({"dialogue-model"}),
        max_unique_voices=4,
    )

    assert speech.supports(ProviderFeature.STREAMING)
    assert not speech.supports(ProviderFeature.TIMESTAMPS)
    assert dialogue.max_unique_voices == 4
