from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import elscript.api as api_module
from elscript import render, render_document, render_yaml
from elscript.audio import decode_audio
from elscript.domain import RenderResult
from elscript.errors import GenerationError, WriteError
from elscript.loading import load_document
from elscript.providers.base import GenerationResult, ProviderCapabilities, ProviderRequest
from elscript.providers.elevenlabs_prompt import elevenlabs_capabilities
from elscript.providers.fake import FakeProvider

FIXTURES = Path(__file__).parent / "fixtures"
SIGNAL_FILE = FIXTURES / "signal_below.yaml"
SIGNAL_PROJECT = FIXTURES / "signal_below"


def _small_document() -> dict[str, object]:
    return {
        "elscript": "1.0",
        "meta": {"id": "equivalent"},
        "render": {
            "provider": "fake",
            "output_format": "wav_16000",
            "timestamps": True,
        },
        "characters": {"MARA": {"voice_id": "voice-mara"}},
        "scenes": [
            {"id": "first", "order": 10, "script": [{"MARA": "First."}]},
            {"id": "second", "order": 20, "script": [{"MARA": "Second."}]},
        ],
        "export": {"mode": "scene"},
    }


def _result_signature(rendered: RenderResult) -> tuple[object, ...]:
    files = rendered.files
    assert rendered.manifest_path is not None
    return (
        tuple(path.name for path in files),
        tuple(path.read_bytes() for path in files),
        json.loads(rendered.manifest_path.read_text(encoding="utf-8")),
        rendered.duration_seconds,
        tuple(scene.id for scene in rendered.scenes),
        tuple(segment.id for segment in rendered.segments),
        rendered.provider_requests,
    )


def test_every_source_form_and_convenience_api_has_identical_render_semantics(
    tmp_path: Path,
) -> None:
    document = _small_document()
    yaml_text = yaml.safe_dump(document, sort_keys=False)
    source_file = tmp_path / "equivalent.yaml"
    source_file.write_text(yaml_text, encoding="utf-8")
    source_project = tmp_path / "project"
    source_project.mkdir()
    (source_project / "meta.yaml").write_text(
        "elscript: '1.0'\nmeta: {id: equivalent}\n"
        "render: {provider: fake, output_format: wav_16000, timestamps: true}\n"
        "export: {mode: scene}\n",
        encoding="utf-8",
    )
    (source_project / "characters.yaml").write_text(
        "characters: {MARA: {voice_id: voice-mara}}\n",
        encoding="utf-8",
    )
    (source_project / "scenes.yaml").write_text(
        yaml.safe_dump({"scenes": document["scenes"]}, sort_keys=False),
        encoding="utf-8",
    )

    results = (
        render(source=source_file, output_dir=tmp_path / "file"),
        render(source=source_project, output_dir=tmp_path / "directory"),
        render_yaml(yaml_text, output_dir=tmp_path / "yaml"),
        render_document(document, output_dir=tmp_path / "mapping"),
    )
    signatures = tuple(_result_signature(result) for result in results)

    assert all(signature == signatures[0] for signature in signatures[1:])
    assert signatures[0][0] == ("first.wav", "second.wav")


@pytest.mark.parametrize(
    ("mode", "expected_count", "expected_first"),
    [
        ("single", 1, "signal-below.wav"),
        ("scene", 1, "station.wav"),
        ("segment", 30, "station_0001_narrator.wav"),
    ],
)
def test_comprehensive_split_project_renders_every_file_mode(
    tmp_path: Path,
    mode: str,
    expected_count: int,
    expected_first: str,
) -> None:
    result = render(
        source=SIGNAL_PROJECT,
        output_dir=tmp_path / mode,
        options={"output_mode": mode},
    )

    assert len(result.files) == expected_count
    assert result.files[0].name == expected_first
    assert result.manifest_path is not None
    assert result.manifest_path.name == "signal-below.manifest.json"
    assert result.duration_seconds == pytest.approx(6.5, abs=1 / 16_000)
    assert len(result.scenes) == 1
    assert len(result.segments) == 30
    assert result.provider_requests == 5
    assert not result.warnings
    assert all(path.is_file() for path in result.files)
    assert all(
        decode_audio(path.read_bytes(), "wav_16000").duration_seconds > 0 for path in result.files
    )
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["output_mode"] == mode
    assert len(payload["segments"]) == 30


def test_single_file_and_split_comprehensive_fixtures_are_logically_identical() -> None:
    single = load_document(source=SIGNAL_FILE)
    split = load_document(source=SIGNAL_PROJECT)

    assert single.data == split.data
    assert len(single.sources) == 1
    assert len(split.sources) == 6


def test_render_result_needs_no_manifest_parsing_and_manifest_can_be_disabled(
    tmp_path: Path,
) -> None:
    result = render(
        source=SIGNAL_FILE,
        output_dir=tmp_path / "segments",
        options={"output_mode": "segment", "manifest_enabled": False},
    )

    assert result.manifest_path is None
    assert len(result.files) == 30
    assert result.scenes[0].files == result.files
    assert [segment.file for segment in result.segments] == list(result.files)
    assert [segment.ordinal for segment in result.segments] == list(range(1, 31))
    assert all(segment.provider_request_id for segment in result.segments)
    assert result.provider_requests == 5
    assert not tuple((tmp_path / "segments").glob("*.json"))


def test_destination_collisions_are_rejected_before_provider_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "audio"
    output.mkdir()
    existing = output / "equivalent.wav"
    existing.write_bytes(b"keep")

    def unexpected_generation(*args: object, **kwargs: object) -> object:
        raise AssertionError("provider generation must not run after a failed preflight")

    monkeypatch.setattr(api_module.FakeProvider, "generate", unexpected_generation)

    with pytest.raises(WriteError, match="Refusing to overwrite"):
        render_document(_small_document(), output_dir=output, options={"output_mode": "single"})
    assert existing.read_bytes() == b"keep"

    manifest_output = tmp_path / "manifest-collision"
    manifest_output.mkdir()
    existing_manifest = manifest_output / "equivalent.manifest.json"
    existing_manifest.write_text("keep", encoding="utf-8")
    with pytest.raises(WriteError, match="existing manifest"):
        render_document(
            _small_document(),
            output_dir=manifest_output,
            options={"output_mode": "single"},
        )
    assert existing_manifest.read_text(encoding="utf-8") == "keep"
    assert not (manifest_output / "equivalent.wav").exists()


def test_generation_and_manifest_failures_leave_no_partial_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_generation(*args: object, **kwargs: object) -> object:
        raise GenerationError("synthetic provider failure")

    generation_output = tmp_path / "generation-failure"
    monkeypatch.setattr(api_module.FakeProvider, "generate", failed_generation)
    with pytest.raises(GenerationError, match="synthetic"):
        render_document(_small_document(), output_dir=generation_output)
    assert not tuple(generation_output.iterdir())

    monkeypatch.undo()

    def failed_manifest(*args: object, **kwargs: object) -> object:
        raise WriteError("synthetic manifest failure")

    manifest_output = tmp_path / "manifest-failure"
    monkeypatch.setattr(api_module, "write_manifest", failed_manifest)
    with pytest.raises(WriteError, match="synthetic manifest"):
        render_document(_small_document(), output_dir=manifest_output)
    assert not tuple(manifest_output.iterdir())


def test_public_pipeline_prepares_elevenlabs_requests_and_returns_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StubElevenLabsProvider:
        def __init__(self) -> None:
            self.generated: list[ProviderRequest] = []
            self.fake = FakeProvider()

        def describe_capabilities(self) -> ProviderCapabilities:
            return elevenlabs_capabilities()

        def generate(self, request: ProviderRequest) -> GenerationResult:
            self.generated.append(request)
            return self.fake.generate(request)

    provider = StubElevenLabsProvider()
    monkeypatch.setattr(
        api_module,
        "ElevenLabsProvider",
        lambda credential: provider,
    )
    document = {
        "elscript": "1.0",
        "meta": {"id": "eleven-path"},
        "render": {
            "provider": "elevenlabs",
            "mode": "speech",
            "model": "eleven_v3",
            "output_format": "wav_16000",
            "timestamps": True,
            "seed": 7,
        },
        "pronunciation": {"terms": {"Calypso": {"ipa": "kəˈlɪpsoʊ"}}},
        "characters": {"MARA": {"voice_id": "voice-mara"}},
        "scenes": [
            {
                "id": "one",
                "script": [
                    {
                        "MARA": {
                            "with": {"volume": "whisper"},
                            "say": "Calypso is listening.",
                        }
                    }
                ],
            }
        ],
    }

    result = render_document(document, output_dir=tmp_path / "eleven")

    assert len(provider.generated) == 1
    part = provider.generated[0].parts[0]
    assert part.translation_version == "elevenlabs-prompt-v1"
    assert part.text is not None
    assert "[whispers]" in part.text
    assert "/kəˈlɪpsoʊ/" in part.text
    assert [warning.code for warning in result.warnings] == ["ELEVENLABS_SEED_BEST_EFFORT"]
    assert result.manifest_path is not None
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [warning["code"] for warning in payload["warnings"]] == ["ELEVENLABS_SEED_BEST_EFFORT"]
