from __future__ import annotations

from pathlib import Path

import pytest

import elscript.api as api_module
import elscript.cache as cache_module
import elscript.output as output_module
from elscript import render_document
from elscript.diagnostics import ERROR_REGISTRY, WARNING_REGISTRY, format_error
from elscript.domain import PipelinePhase
from elscript.errors import ELScriptError, GenerationError
from elscript.providers.base import GenerationResult, ProviderCapabilities, ProviderRequest
from elscript.providers.fake import FakeProvider, fake_capabilities


def _document(
    *,
    script_id: str = "failure-story",
    seed: int = 17,
) -> dict[str, object]:
    return {
        "elscript": "1.0",
        "meta": {"id": script_id},
        "render": {
            "provider": "fake",
            "mode": "speech",
            "output_format": "wav_16000",
            "seed": seed,
        },
        "characters": {"MARA": {"voice_id": "mara-voice"}},
        "scenes": [
            {
                "id": "one",
                "script": [
                    {"MARA": {"id": "first", "say": "One."}},
                    {"MARA": {"id": "second", "say": "Two."}},
                ],
            }
        ],
        "export": {"mode": "segment"},
    }


def _error_classes(root: type[ELScriptError]) -> set[type[ELScriptError]]:
    result = {root}
    for child in root.__subclasses__():
        result.update(_error_classes(child))
    return result


def test_diagnostic_registry_covers_hierarchy_phases_and_troubleshooting() -> None:
    class_codes = {error.default_code for error in _error_classes(ELScriptError)}
    registered_phases = {
        phase
        for code, definition in ERROR_REGISTRY.items()
        if code != "ELSCRIPT_ERROR"
        for phase in definition.phases
    }
    troubleshooting = (Path(__file__).parents[1] / "docs" / "troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert set(ERROR_REGISTRY) == class_codes
    assert registered_phases == set(PipelinePhase)
    assert set(ERROR_REGISTRY).isdisjoint(WARNING_REGISTRY)
    assert all(definition.severity == "warning" for definition in WARNING_REGISTRY.values())
    assert all(f"`{code}`" in troubleshooting for code in ERROR_REGISTRY)
    assert all(f"`{code}`" in troubleshooting for code in WARNING_REGISTRY)
    assert all(f"`{phase.value}`" in troubleshooting for phase in PipelinePhase)


def test_error_format_contains_phase_code_context_and_correction() -> None:
    error = GenerationError(
        "Provider returned no usable audio",
        context={"provider": "fake", "segment_id": "one.mara.0001"},
    )

    rendered = format_error(error)

    assert "[provider_generation/GENERATION_ERROR]" in rendered
    assert "provider='fake'" in rendered
    assert "segment_id='one.mara.0001'" in rendered
    assert "Correction:" in rendered


def test_unexpected_provider_exception_is_stable_and_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenProvider:
        provider_id = "fake"

        def describe_capabilities(self) -> ProviderCapabilities:
            return fake_capabilities()

        def generate(self, request: ProviderRequest) -> GenerationResult:
            raise RuntimeError("socket echoed private-provider-value")

    monkeypatch.setattr(api_module, "FakeProvider", BrokenProvider)
    output = tmp_path / "failed"

    with pytest.raises(GenerationError) as caught:
        render_document(_document(), output_dir=output)

    assert caught.value.code == "GENERATION_ERROR"
    assert caught.value.phase is PipelinePhase.PROVIDER_GENERATION
    assert caught.value.context["provider"] == "fake"
    assert "private-provider-value" not in str(caught.value)
    assert not tuple(output.iterdir())


def test_partial_provider_failure_does_not_touch_prior_render_or_publish_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = render_document(_document(script_id="prior"), output_dir=tmp_path / "prior")
    prior_bytes = {path.name: path.read_bytes() for path in prior.files}

    class FailsSecondRequest:
        provider_id = "fake"

        def __init__(self) -> None:
            self.fake = FakeProvider()
            self.calls = 0

        def describe_capabilities(self) -> ProviderCapabilities:
            return fake_capabilities()

        def generate(self, request: ProviderRequest) -> GenerationResult:
            self.calls += 1
            if self.calls == 2:
                raise GenerationError("synthetic provider failure")
            return self.fake.generate(request)

    provider = FailsSecondRequest()
    monkeypatch.setattr(api_module, "FakeProvider", lambda: provider)
    failed = tmp_path / "failed"

    with pytest.raises(GenerationError, match="synthetic"):
        render_document(_document(script_id="new", seed=99), output_dir=failed)

    assert {path.name: path.read_bytes() for path in prior.files} == prior_bytes
    assert not tuple(failed.iterdir())
    cache_records = tuple((tmp_path / ".cache" / "elscript").glob("*/*.json"))
    assert len(cache_records) == 2


def test_mid_publish_failure_removes_final_and_temporary_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_link = output_module.os.link
    calls = 0

    def fail_second_link(source: object, destination: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic disk failure")
        real_link(source, destination)

    monkeypatch.setattr(output_module.os, "link", fail_second_link)
    output = tmp_path / "partial"

    with pytest.raises(ELScriptError) as caught:
        render_document(_document(), output_dir=output)

    assert caught.value.code == "WRITE_ERROR"
    assert not tuple(output.iterdir())


def test_manifest_cancellation_removes_new_audio_and_preserves_prior_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = render_document(_document(script_id="prior"), output_dir=tmp_path / "prior")
    prior_bytes = {path.name: path.read_bytes() for path in prior.files}

    def cancel_manifest(*args: object, **kwargs: object) -> Path:
        raise KeyboardInterrupt

    monkeypatch.setattr(api_module, "write_manifest", cancel_manifest)
    cancelled = tmp_path / "cancelled"

    with pytest.raises(KeyboardInterrupt):
        render_document(_document(script_id="cancelled"), output_dir=cancelled)

    assert not tuple(cancelled.iterdir())
    assert {path.name: path.read_bytes() for path in prior.files} == prior_bytes


def test_cache_publication_cancellation_removes_temporary_cache_and_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cancel_cache_publish(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cache_module.os, "replace", cancel_cache_publish)
    output = tmp_path / "cancelled-cache"

    with pytest.raises(KeyboardInterrupt):
        render_document(_document(), output_dir=output)

    assert not tuple(output.iterdir())
    cache_root = tmp_path / ".cache" / "elscript"
    assert not tuple(path for path in cache_root.rglob("*") if path.is_file())
