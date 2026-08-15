from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

import elscript
from elscript import render, render_yaml
from elscript.audio import decode_audio

ROOT = Path(__file__).parents[1]
README = ROOT / "README.md"
SIGNAL_FILE = ROOT / "tests" / "fixtures" / "signal_below.yaml"
SIGNAL_PROJECT = ROOT / "tests" / "fixtures" / "signal_below"
FAKE_OPTIONS = {
    "provider": "fake",
    "model": "fake-model",
    "output_format": "wav_16000",
}


def _marked_fence(name: str, language: str) -> str:
    text = README.read_text(encoding="utf-8")
    marked = text.split(f"<!-- test:{name} -->", 1)[1].split(
        f"<!-- /test:{name} -->", 1
    )[0]
    return marked.split(f"```{language}", 1)[1].split("```", 1)[0].strip()


def test_readme_quick_start_runs_through_canonical_pipeline(tmp_path: Path) -> None:
    result = render_yaml(
        _marked_fence("quick-start-yaml", "yaml"),
        output_dir=tmp_path / "quick-start",
        options=FAKE_OPTIONS,
    )

    assert len(result.files) == 1
    assert result.manifest_path is not None
    assert result.manifest_path.name == "first-story.manifest.json"
    assert decode_audio(result.files[0].read_bytes(), "wav_16000").duration_seconds > 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["script_id"] == "first-story"
    assert manifest["provider"] == "fake"
    assert len(manifest["segments"]) == 3


def test_comprehensive_single_and_project_examples_render_equivalently(
    tmp_path: Path,
) -> None:
    options = {**FAKE_OPTIONS, "output_mode": "segment", "timestamps": True}
    single = render(
        source=SIGNAL_FILE,
        output_dir=tmp_path / "single",
        options=options,
    )
    project = render(
        source=SIGNAL_PROJECT,
        output_dir=tmp_path / "project",
        options=options,
    )

    assert len(single.files) == len(project.files) == 30
    assert single.duration_seconds == pytest.approx(project.duration_seconds)
    assert [path.name for path in single.files] == [path.name for path in project.files]
    assert [path.read_bytes() for path in single.files] == [
        path.read_bytes() for path in project.files
    ]
    assert [
        (segment.id, segment.scene_id, segment.ordinal, segment.speaker)
        for segment in single.segments
    ] == [
        (segment.id, segment.scene_id, segment.ordinal, segment.speaker)
        for segment in project.segments
    ]


def test_readme_relative_links_and_release_docs_exist() -> None:
    text = README.read_text(encoding="utf-8")
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
    relative = [link for link in links if "://" not in link and not link.startswith("#")]

    assert relative
    assert all((ROOT / link).exists() for link in relative)
    assert "opt-in credentialed smoke" in (ROOT / "docs" / "releasing.md").read_text(
        encoding="utf-8"
    ).casefold()


def test_package_metadata_version_and_public_files_are_synchronized() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert metadata["name"] == "elscript"
    assert metadata["version"] == elscript.__version__
    assert metadata["requires-python"] == ">=3.11"
    assert metadata["scripts"] == {"elscript": "elscript.cli:main"}
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert "## [0.1.0a0]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
