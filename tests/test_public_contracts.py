from __future__ import annotations

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

import elscript
from elscript.domain import AudioChunk, PipelinePhase
from elscript.errors import (
    AssemblyError,
    AudioError,
    AuthenticationError,
    CapabilityError,
    CompileError,
    DecodeError,
    ELScriptError,
    FilenameCollisionError,
    GenerationError,
    InputError,
    InvalidStateError,
    InvalidYamlError,
    MergeConflictError,
    MergeError,
    OutputError,
    ProviderError,
    ProviderLimitError,
    RateLimitError,
    SchemaError,
    SourceNotFoundError,
    UnknownCharacterError,
    UnknownPresetError,
    UnsupportedModelFeatureError,
    UnsupportedOutputFormatError,
    ValidationError,
    WriteError,
)


def test_public_api_exports_stable_entry_points_and_types() -> None:
    expected = {
        "render",
        "render_yaml",
        "render_document",
        "stream",
        "astream",
        "RenderResult",
        "AudioChunk",
    }

    assert expected <= set(elscript.__all__)
    assert all(hasattr(elscript, name) for name in expected)
    assert dataclasses.is_dataclass(elscript.RenderResult)
    assert dataclasses.is_dataclass(elscript.AudioChunk)


@pytest.mark.parametrize(
    ("category", "children"),
    [
        (InputError, (SourceNotFoundError, InvalidYamlError)),
        (MergeError, (MergeConflictError,)),
        (SchemaError, (ValidationError,)),
        (CompileError, (UnknownCharacterError, UnknownPresetError, InvalidStateError)),
        (
            CapabilityError,
            (UnsupportedModelFeatureError, UnsupportedOutputFormatError, ProviderLimitError),
        ),
        (ProviderError, (AuthenticationError, RateLimitError, GenerationError)),
        (AudioError, (DecodeError, AssemblyError)),
        (OutputError, (FilenameCollisionError, WriteError)),
    ],
)
def test_error_categories_are_programmatically_catchable(
    category: type[ELScriptError], children: tuple[type[ELScriptError], ...]
) -> None:
    assert issubclass(category, ELScriptError)
    assert all(issubclass(child, category) for child in children)


def test_errors_include_phase_and_redact_sensitive_context() -> None:
    error = AuthenticationError(
        "provider rejected the request",
        context={"api_key": "super-secret", "status": 401},
    )

    assert error.phase is PipelinePhase.PROVIDER_GENERATION
    assert error.context == {"api_key": "<redacted>", "status": 401}
    assert "super-secret" not in str(error)


def test_audio_chunk_requires_audio_or_an_event() -> None:
    with pytest.raises(ValueError, match="audio data or an event"):
        AudioChunk(data=b"", format="mp3_44100_128")

    event = AudioChunk(data=b"", format="mp3_44100_128", event="marker")
    assert event.event == "marker"


def test_render_rejects_ambiguous_source_selection() -> None:
    with pytest.raises(InputError, match="Exactly one"):
        elscript.render(source="story.yaml", yaml_text="elscript: '1.0'", output_dir="audio")


def test_cli_help_describes_file_rendering_without_streaming() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "elscript.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "ELScript YAML file or project directory" in completed.stdout
    assert "--output DIRECTORY" in completed.stdout
    assert "--mode" in completed.stdout
    assert "--stream" not in completed.stdout


def test_distribution_name_and_version_are_exposed() -> None:
    assert elscript.__version__ == "0.1.0a0"
    assert Path(elscript.__file__).parent.name == "elscript"
