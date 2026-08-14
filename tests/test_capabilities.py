from __future__ import annotations

from dataclasses import replace

import pytest

from elscript.compiler import compile_document
from elscript.config import resolve_config
from elscript.errors import (
    CapabilityError,
    ProviderLimitError,
    UnsupportedModelFeatureError,
    UnsupportedOutputFormatError,
)
from elscript.loading import load_document
from elscript.planner import plan_render
from elscript.providers.base import (
    DictionaryLocator,
    EndpointCapabilities,
    Provider,
    ProviderCapabilities,
    ProviderFeature,
)
from elscript.providers.fake import FakeProvider, fake_capabilities
from elscript.validation import validate_document


def _compiled_config(
    *,
    render: dict[str, object] | None = None,
    output_mode: str = "single",
):  # type: ignore[no-untyped-def]
    document = validate_document(
        load_document(
            document={
                "elscript": "1.0",
                "render": render or {},
                "characters": {
                    "MARA": {"voice_id": "mara"},
                    "ORION": {"voice_id": "orion"},
                },
                "scenes": [
                    {"id": "scene", "script": [{"MARA": "One"}, {"ORION": "Two"}]}
                ],
                "export": {"mode": output_mode},
            }
        )
    )
    config = resolve_config(document, process_env={}, options={"provider": "fake"})
    return compile_document(document, config), config


def test_explicit_dialogue_fails_when_endpoint_is_unavailable() -> None:
    compiled, config = _compiled_config(render={"mode": "dialogue"})
    capabilities = replace(fake_capabilities(), dialogue=None)

    with pytest.raises(UnsupportedModelFeatureError, match="no dialogue endpoint"):
        plan_render(compiled, config, capabilities)


def test_requested_streaming_fails_before_generation_when_unsupported() -> None:
    compiled, config = _compiled_config(render={"mode": "speech"})
    capabilities = fake_capabilities()
    assert capabilities.speech is not None
    capabilities = replace(
        capabilities,
        speech=replace(
            capabilities.speech,
            features=capabilities.speech.features - {ProviderFeature.STREAMING},
        ),
    )

    with pytest.raises(UnsupportedModelFeatureError, match="do not support streaming"):
        plan_render(compiled, config, capabilities, streaming=True)


def test_unsupported_output_format_and_model_fail_before_generation() -> None:
    compiled, config = _compiled_config(render={"mode": "speech"})
    capabilities = fake_capabilities()
    assert capabilities.speech is not None

    wrong_format = replace(
        capabilities,
        speech=replace(
            capabilities.speech,
            supported_output_formats=frozenset({"wav_16000"}),
        ),
    )
    with pytest.raises(UnsupportedOutputFormatError, match="not supported"):
        plan_render(compiled, config, wrong_format)

    wrong_model = replace(
        capabilities,
        speech=replace(
            capabilities.speech,
            supported_models=frozenset({"other-model"}),
        ),
    )
    with pytest.raises(UnsupportedModelFeatureError, match="does not support speech"):
        plan_render(compiled, config, wrong_model)


def test_dictionary_support_and_limits_are_never_silently_degraded() -> None:
    compiled, config = _compiled_config(render={"mode": "speech"})
    dictionaries = tuple(DictionaryLocator(f"dict-{index}", "v1") for index in range(4))

    with pytest.raises(ProviderLimitError, match="at most 3"):
        plan_render(compiled, config, fake_capabilities(), dictionaries=dictionaries)

    capabilities = fake_capabilities()
    assert capabilities.speech is not None
    capabilities = replace(
        capabilities,
        speech=replace(
            capabilities.speech,
            features=capabilities.speech.features
            - {ProviderFeature.PRONUNCIATION_DICTIONARIES},
        ),
    )
    with pytest.raises(UnsupportedModelFeatureError, match="do not support"):
        plan_render(
            compiled,
            config,
            capabilities,
            dictionaries=(DictionaryLocator("dictionary", "v1"),),
        )


def test_explicit_dialogue_cannot_hide_missing_segment_attribution() -> None:
    compiled, config = _compiled_config(render={"mode": "dialogue"}, output_mode="segment")
    capabilities = fake_capabilities()
    assert capabilities.dialogue is not None
    capabilities = replace(
        capabilities,
        dialogue=replace(
            capabilities.dialogue,
            features=capabilities.dialogue.features - {ProviderFeature.SPEAKER_SEGMENTS},
        ),
    )

    with pytest.raises(UnsupportedModelFeatureError, match="cannot be attributed"):
        plan_render(compiled, config, capabilities)


def test_provider_identity_mismatch_is_actionable() -> None:
    compiled, config = _compiled_config()
    capabilities = ProviderCapabilities(
        provider_id="someone-else",
        speech=EndpointCapabilities(),
    )

    with pytest.raises(CapabilityError, match="does not match"):
        plan_render(compiled, config, capabilities)


def test_fake_provider_is_protocol_compatible_deterministic_and_no_network() -> None:
    compiled, config = _compiled_config()
    first_provider = FakeProvider()
    second_provider = FakeProvider()
    request = plan_render(
        compiled,
        config,
        first_provider.describe_capabilities(),
    ).requests[0]

    assert first_provider.requests == ()

    first = first_provider.generate(request)
    second = second_provider.generate(request)
    chunks = tuple(second_provider.stream(request))

    assert isinstance(first_provider, Provider)
    assert first.audio == second.audio
    assert first.request_id == second.request_id
    assert first.metadata == {"deterministic": True}
    assert chunks[0].audio == first.audio
    assert chunks[0].final is True
    assert len(first_provider.requests) == 1
    assert len(second_provider.requests) == 2
