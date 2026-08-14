from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import elscript.cli as cli
from elscript.domain import (
    Diagnostic,
    DiagnosticSeverity,
    PipelinePhase,
    RenderOptions,
    RenderResult,
)

FIXTURES = Path(__file__).parent / "fixtures"
SIGNAL_PROJECT = FIXTURES / "signal_below"


def _run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "elscript.cli", *(str(value) for value in arguments)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_renders_comprehensive_project_and_prints_assets_and_manifest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "audio"

    completed = _run_cli(SIGNAL_PROJECT, "--output", output, "--mode", "segment")

    assert completed.returncode == 0
    assert completed.stderr == ""
    printed = completed.stdout.splitlines()
    assert len(printed) == 31
    assert Path(printed[0]).name == "station_0001_narrator.wav"
    assert Path(printed[-1]).name == "signal-below.manifest.json"
    assert all(Path(item).is_file() for item in printed)


def test_cli_overrides_use_public_configuration_precedence(tmp_path: Path) -> None:
    source = tmp_path / "story.yaml"
    source.write_text(
        """\
elscript: "1.0"
meta: {id: cli-story}
render:
  provider: fake
  model: yaml-model
  output_format: mp3_44100_128
  seed: 1
characters:
  MARA: {voice_id: mara}
scenes:
  - id: opening
    script:
      - MARA: Hello.
export: {mode: single}
""",
        encoding="utf-8",
    )
    output = tmp_path / "override"

    completed = _run_cli(
        source,
        "--output",
        output,
        "--mode",
        "scene",
        "--model",
        "cli-model",
        "--format",
        "wav_16000",
        "--seed",
        42,
    )

    assert completed.returncode == 0
    assert {path.name for path in output.iterdir()} == {
        "opening.wav",
        "cli-story.manifest.json",
    }
    manifest = json.loads((output / "cli-story.manifest.json").read_text(encoding="utf-8"))
    settings = manifest["effective_settings"]
    assert settings["output_mode"] == "scene"
    assert settings["model"] == "cli-model"
    assert settings["output_format"] == "wav_16000"
    assert settings["seed"] == 42


def test_cli_errors_include_phase_source_context_and_actionable_message(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.yaml"
    missing_result = _run_cli(missing, "--output", tmp_path / "missing-output")

    assert missing_result.returncode == 1
    assert "[source_discovery]" in missing_result.stderr
    assert "SOURCE_NOT_FOUND" in missing_result.stderr
    assert str(missing) in missing_result.stderr
    assert "does not exist" in missing_result.stderr

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        "elscript: '1.0'\ncharacters: {}\nscenes:\n  - id: one\n    script:\n      - GHOST: Boo\n",
        encoding="utf-8",
    )
    invalid_result = _run_cli(invalid, "--output", tmp_path / "invalid-output")

    assert invalid_result.returncode == 1
    assert "[reference_validation]" in invalid_result.stderr
    assert "UNKNOWN_CHARACTER" in invalid_result.stderr
    assert str(invalid) in invalid_result.stderr
    assert "GHOST" in invalid_result.stderr


def test_cli_is_a_thin_public_render_wrapper_and_emits_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}
    audio = (tmp_path / "audio.wav").resolve()
    manifest = (tmp_path / "story.manifest.json").resolve()
    warning = Diagnostic(
        code="W-CLI",
        message="Best-effort setting",
        severity=DiagnosticSeverity.WARNING,
        phase=PipelinePhase.CAPABILITY_VALIDATION,
    )

    def fake_render(**kwargs: object) -> RenderResult:
        captured.update(kwargs)
        return RenderResult(
            files=(audio,),
            manifest_path=manifest,
            duration_seconds=0.1,
            warnings=(warning,),
        )

    monkeypatch.setattr(cli, "render", fake_render)

    exit_code = cli.main(
        [
            "story.yaml",
            "--output",
            str(tmp_path),
            "--mode",
            "segment",
            "--seed",
            "7",
        ]
    )

    streams = capsys.readouterr()
    assert exit_code == 0
    assert streams.out.splitlines() == [str(audio), str(manifest)]
    assert "capability_validation/W-CLI" in streams.err
    assert captured["source"] == Path("story.yaml")
    assert captured["output_dir"] == tmp_path
    options = captured["options"]
    assert isinstance(options, RenderOptions)
    assert options.output_mode == "segment"
    assert options.seed == 7


def test_cli_help_has_no_streaming_path() -> None:
    completed = _run_cli("--help")

    assert completed.returncode == 0
    assert "--stream" not in completed.stdout
    assert "--output DIRECTORY" in completed.stdout
