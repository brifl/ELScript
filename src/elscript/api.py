"""Public API entry points.

The boundary is intentionally available before the rendering pipeline lands so
applications can type against it during the pre-alpha implementation phase.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from pathlib import Path
from typing import Any, NoReturn

from .domain import AudioChunk, RenderOptions, RenderResult
from .errors import InputError

SourcePath = str | Path
OptionsInput = RenderOptions | Mapping[str, Any]


def _validate_source_choice(
    source: SourcePath | None,
    yaml_text: str | None,
    document: Mapping[str, Any] | None,
) -> None:
    supplied = sum(value is not None for value in (source, yaml_text, document))
    if supplied != 1:
        raise InputError("Exactly one of source, yaml_text, or document must be supplied")


def _pipeline_unavailable() -> NoReturn:
    raise NotImplementedError(
        "ELScript is pre-alpha; the rendering pipeline is being implemented in checkpoints 1.2-2.6"
    )


def render(
    *,
    source: SourcePath | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    output_dir: SourcePath,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> RenderResult:
    """Render exactly one supported source form to files in ``output_dir``."""

    _validate_source_choice(source, yaml_text, document)
    _pipeline_unavailable()


def render_yaml(
    yaml_text: str,
    *,
    output_dir: SourcePath,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> RenderResult:
    """Render YAML text through the canonical pipeline."""

    return render(
        yaml_text=yaml_text,
        output_dir=output_dir,
        options=options,
        env_file=env_file,
    )


def render_document(
    document: Mapping[str, Any],
    *,
    output_dir: SourcePath,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> RenderResult:
    """Render an already parsed mapping through the canonical pipeline."""

    return render(
        document=document,
        output_dir=output_dir,
        options=options,
        env_file=env_file,
    )


def stream(
    *,
    source: SourcePath | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> Iterator[AudioChunk]:
    """Stream attributed chunks through the canonical pipeline."""

    _validate_source_choice(source, yaml_text, document)
    _pipeline_unavailable()
    yield  # pragma: no cover - keeps the public return type an iterator


async def astream(
    *,
    source: SourcePath | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> AsyncIterator[AudioChunk]:
    """Asynchronously stream attributed chunks through the canonical pipeline."""

    _validate_source_choice(source, yaml_text, document)
    _pipeline_unavailable()
    yield  # pragma: no cover - keeps the public return type an async iterator
