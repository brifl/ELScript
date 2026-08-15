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
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
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


def test_readme_repository_links_and_release_docs_exist() -> None:
    text = README.read_text(encoding="utf-8")
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", text)
    repository_prefixes = (
        "https://github.com/brifl/ELScript/blob/main/",
        "https://github.com/brifl/ELScript/tree/main/",
    )
    repository_paths = [
        link.removeprefix(prefix)
        for link in links
        for prefix in repository_prefixes
        if link.startswith(prefix)
    ]

    assert repository_paths
    assert all((ROOT / path).exists() for path in repository_paths)
    assert "opt-in credentialed smoke" in (ROOT / "docs" / "releasing.md").read_text(
        encoding="utf-8"
    ).casefold()


def test_package_metadata_version_and_public_files_are_synchronized() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert metadata["name"] == "elscript-audio"
    assert metadata["version"] == elscript.__version__
    assert metadata["requires-python"] == ">=3.11"
    classifiers = set(metadata["classifiers"])
    assert {
        f"Programming Language :: Python :: 3.{minor}" for minor in range(11, 15)
    } <= classifiers
    assert metadata["scripts"] == {"elscript": "elscript.cli:main"}
    readme = README.read_text(encoding="utf-8")
    assert "No PyPI release has been published yet" in " ".join(readme.split())
    assert not re.search(r"^pip install elscript$", readme, re.MULTILINE)
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
    assert "## [0.1.0a0]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_ci_covers_supported_runtimes_without_release_authority() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in workflow
    assert 'python-version: "3.14"' in workflow
    assert workflow.count("actions/checkout@v6") == 2
    assert workflow.count("actions/setup-python@v6") == 2
    assert workflow.count("actions/upload-artifact@v6") == 1
    assert "permissions:\n  contents: read" in workflow
    assert "pip show elscript-audio" in workflow
    assert not any(
        forbidden in workflow
        for forbidden in (
            "ELEVENLABS_API_KEY",
            "pypa/gh-action-pypi-publish",
            "twine upload",
            "contents: write",
            "id-token: write",
        )
    )
