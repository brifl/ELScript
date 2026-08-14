"""Stable data contracts shared across ELScript pipeline phases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class PipelinePhase(StrEnum):
    """Observable processing phases used by diagnostics and errors."""

    SOURCE_DISCOVERY = "source_discovery"
    YAML_PARSING = "yaml_parsing"
    LOGICAL_MERGE = "logical_merge"
    SCHEMA_VALIDATION = "schema_validation"
    REFERENCE_VALIDATION = "reference_validation"
    SEMANTIC_COMPILATION = "semantic_compilation"
    CAPABILITY_VALIDATION = "capability_validation"
    PROVIDER_GENERATION = "provider_generation"
    AUDIO_ASSEMBLY = "audio_assembly"
    OUTPUT_WRITING = "output_writing"


class DiagnosticSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class OutputMode(StrEnum):
    SINGLE = "single"
    SCENE = "scene"
    SEGMENT = "segment"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Best-known source coordinates for an authored value."""

    source: str
    yaml_path: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A stable machine-readable warning or error receipt."""

    code: str
    message: str
    severity: DiagnosticSeverity
    phase: PipelinePhase
    location: SourceLocation | None = None
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RenderOptions:
    """Explicit caller overrides; ``None`` means the layer supplied no value."""

    provider: str | None = None
    model: str | None = None
    output_format: str | None = None
    output_mode: OutputMode | str | None = None
    seed: int | None = None
    timestamps: bool | None = None
    text_normalization: str | None = None
    language_text_normalization: bool | None = None
    enable_logging: bool | None = None


@dataclass(frozen=True, slots=True)
class SceneResult:
    id: str
    files: tuple[Path, ...] = ()
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class SegmentResult:
    id: str
    scene_id: str
    ordinal: int
    speaker: str
    file: Path | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None
    provider_request_id: str | None = None
    render_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Structured result returned by file rendering entry points."""

    files: tuple[Path, ...]
    manifest_path: Path | None
    duration_seconds: float
    scenes: tuple[SceneResult, ...] = ()
    segments: tuple[SegmentResult, ...] = ()
    provider_requests: int = 0
    warnings: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """One attributed piece of streamed audio or a timeline event."""

    data: bytes
    format: str
    scene_id: str | None = None
    segment_id: str | None = None
    ordinal: int | None = None
    speaker: str | None = None
    final_for_segment: bool = False
    event: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ordinal is not None and self.ordinal < 1:
            raise ValueError("AudioChunk ordinal must be positive when supplied")
        if not self.data and self.event is None:
            raise ValueError("An AudioChunk must contain audio data or an event")


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    """Canonical mapping plus source provenance produced by source loading."""

    data: Mapping[str, Any]
    sources: tuple[Path, ...]
    provenance: Mapping[str, SourceLocation] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    """Smallest authored vocal unit with one resolved state."""

    id: str
    scene_id: str
    ordinal: int
    speaker: str
    text: str | None
    performance: Mapping[str, Any]
    provider_options: Mapping[str, Any] = field(default_factory=dict)
    cues: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    type: str
    scene_id: str
    after_ordinal: int
    value: str | float | None = None
