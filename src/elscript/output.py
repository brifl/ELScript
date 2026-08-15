"""Safe deterministic naming and materialization of rendered audio outputs."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .audio import (
    AudioAssemblyResult,
    AudioClip,
    PCMBuffer,
    Silence,
    assemble_audio,
    assemble_pcm,
    decode_audio,
    format_extension,
    parse_output_format,
    slice_audio,
)
from .domain import CompiledScript, PauseEvent, SpeechSegment
from .errors import AssemblyError, FilenameCollisionError, WriteError
from .planner import RenderPlan
from .providers.base import GenerationResult, ProviderRequest, RequestKind

_INVALID_FILENAME_CHARACTER = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_WHITESPACE = re.compile(r"\s+")
_DASHES = re.compile(r"-+")
_MAX_COMPONENT_LENGTH = 80
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


@dataclass(frozen=True, slots=True)
class OutputTarget:
    filename: str
    scene_id: str | None = None
    segment_id: str | None = None
    ordinal: int | None = None
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class WrittenAudio:
    path: Path
    duration_seconds: float
    scene_id: str | None = None
    segment_id: str | None = None
    ordinal: int | None = None
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class OutputWriteResult:
    files: tuple[Path, ...]
    artifacts: tuple[WrittenAudio, ...]
    output_mode: str
    output_format: str
    extension: str
    normalize_loudness: bool
    normalization: str | None


@dataclass(frozen=True, slots=True)
class OutputPreflight:
    """Resolved collision-free output paths checked before provider generation."""

    root: Path
    targets: tuple[OutputTarget, ...]
    paths: tuple[Path, ...]


def sanitize_filename_component(
    value: str,
    *,
    fallback: str = "output",
    lowercase: bool = False,
) -> str:
    """Return one readable cross-platform component without traversal semantics."""

    normalized = unicodedata.normalize("NFKC", value)
    if lowercase:
        normalized = normalized.casefold()
    normalized = _INVALID_FILENAME_CHARACTER.sub("-", normalized)
    normalized = _WHITESPACE.sub("-", normalized)
    normalized = _DASHES.sub("-", normalized).strip(" .-_")
    if not normalized or normalized in {".", ".."}:
        normalized = fallback
    if normalized.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    if len(normalized) > _MAX_COMPONENT_LENGTH:
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        normalized = f"{normalized[: _MAX_COMPONENT_LENGTH - 13].rstrip(' .-_')}-{digest}"
    return normalized


def _validate_unique(targets: Sequence[OutputTarget]) -> None:
    by_name: dict[str, OutputTarget] = {}
    for target in targets:
        key = unicodedata.normalize("NFKC", target.filename).casefold()
        previous = by_name.get(key)
        if previous is not None:
            raise FilenameCollisionError(
                f"Output filename {target.filename!r} is not unique after sanitization",
                context={
                    "filename": target.filename,
                    "first_scene_id": previous.scene_id,
                    "second_scene_id": target.scene_id,
                    "first_segment_id": previous.segment_id,
                    "second_segment_id": target.segment_id,
                },
            )
        by_name[key] = target


def segment_output_filename(
    segment: SpeechSegment,
    *,
    max_ordinal: int,
    output_format: str,
) -> str:
    width = max(4, len(str(max_ordinal)))
    scene = sanitize_filename_component(segment.scene_id, fallback="scene")
    speaker = sanitize_filename_component(
        segment.speaker,
        fallback="speaker",
        lowercase=True,
    )
    return f"{scene}_{segment.ordinal:0{width}d}_{speaker}.{format_extension(output_format)}"


def build_output_targets(
    compiled: CompiledScript,
    output_mode: str,
    output_format: str,
) -> tuple[OutputTarget, ...]:
    """Resolve filenames before any filesystem mutation or audio encoding."""

    extension = format_extension(output_format)
    targets: tuple[OutputTarget, ...]
    if output_mode == "single":
        targets = (OutputTarget(f"{sanitize_filename_component(compiled.script_id)}.{extension}"),)
    elif output_mode == "scene":
        targets = tuple(
            OutputTarget(
                f"{sanitize_filename_component(scene.id, fallback='scene')}.{extension}",
                scene_id=scene.id,
            )
            for scene in compiled.scenes
        )
    elif output_mode == "segment":
        max_ordinal = max((item.ordinal for item in compiled.segments), default=0)
        targets = tuple(
            OutputTarget(
                filename=segment_output_filename(
                    segment,
                    max_ordinal=max_ordinal,
                    output_format=output_format,
                ),
                scene_id=segment.scene_id,
                segment_id=segment.id,
                ordinal=segment.ordinal,
                speaker=segment.speaker,
            )
            for segment in compiled.segments
        )
    else:
        raise WriteError(
            f"Unknown output mode {output_mode!r}",
            context={"output_mode": output_mode},
        )
    _validate_unique(targets)
    return targets


def _validate_results(
    plan: RenderPlan,
    results: Mapping[str, GenerationResult],
) -> None:
    expected = {request.id for request in plan.requests}
    actual = set(results)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise AssemblyError(
            "Generation results do not match the render plan",
            context={"missing_request_ids": missing, "unexpected_request_ids": unexpected},
        )
    for request in plan.requests:
        result = results[request.id]
        if result.output_format != request.output_format:
            raise AssemblyError(
                "Provider result format does not match its planned request",
                context={
                    "request_id": request.id,
                    "planned_format": request.output_format,
                    "result_format": result.output_format,
                },
            )
        if not result.audio:
            raise AssemblyError(
                "Provider result contains no audio",
                context={"request_id": request.id},
            )


def _timeline_parts(
    plan: RenderPlan,
    results: Mapping[str, GenerationResult],
    *,
    scene_id: str | None = None,
) -> tuple[AudioClip | Silence, ...]:
    parts: list[AudioClip | Silence] = []
    for event in plan.timeline:
        if event.scene_id != scene_id and scene_id is not None:
            continue
        if isinstance(event, ProviderRequest):
            result = results[event.id]
            parts.append(AudioClip(result.audio, result.output_format))
        elif isinstance(event, PauseEvent):
            parts.append(Silence(event.duration_seconds))
    return tuple(parts)


def _append_dialogue_parts(
    request: ProviderRequest,
    result: GenerationResult,
    decoded: PCMBuffer,
    buffers: dict[str, list[PCMBuffer]],
) -> None:
    if not result.voice_segments:
        raise AssemblyError(
            "Dialogue segment output requires voice-segment timestamps",
            context={"request_id": request.id},
        )
    seen: set[int] = set()
    previous_end = 0.0
    tolerance = 1 / decoded.sample_rate
    for metadata in sorted(result.voice_segments, key=lambda item: item.start_seconds):
        index = metadata.part_index
        if index is None or not 0 <= index < len(request.parts):
            raise AssemblyError(
                "Dialogue voice metadata references an unknown input",
                context={"request_id": request.id, "part_index": index},
            )
        if metadata.start_seconds < previous_end - tolerance:
            raise AssemblyError(
                "Dialogue voice metadata overlaps out of order",
                context={"request_id": request.id, "part_index": index},
            )
        part = request.parts[index]
        if metadata.voice_id != part.segment.voice_id:
            raise AssemblyError(
                "Dialogue voice metadata does not match the planned voice",
                context={"request_id": request.id, "part_index": index},
            )
        buffers[part.logical_id].append(
            slice_audio(decoded, metadata.start_seconds, metadata.end_seconds)
        )
        seen.add(index)
        previous_end = metadata.end_seconds
    missing = sorted(set(range(len(request.parts))) - seen)
    if missing:
        raise AssemblyError(
            "Dialogue voice metadata omitted planned inputs",
            context={"request_id": request.id, "missing_part_indices": missing},
        )


def _segment_audio(
    compiled: CompiledScript,
    plan: RenderPlan,
    results: Mapping[str, GenerationResult],
    output_format: str,
    *,
    normalize_loudness: bool,
) -> dict[str, AudioAssemblyResult]:
    rate = parse_output_format(output_format).sample_rate
    buffers: dict[str, list[PCMBuffer]] = defaultdict(list)
    for request in plan.requests:
        result = results[request.id]
        decoded = decode_audio(
            result.audio,
            result.output_format,
            target_sample_rate=rate,
        )
        if request.kind is RequestKind.SPEECH:
            if len(request.parts) != 1:
                raise AssemblyError(
                    "Speech request must map to exactly one planned part",
                    context={"request_id": request.id},
                )
            buffers[request.parts[0].logical_id].append(decoded)
        else:
            _append_dialogue_parts(request, result, decoded, buffers)

    assembled: dict[str, AudioAssemblyResult] = {}
    for segment in compiled.segments:
        pieces = buffers.get(segment.id)
        if not pieces:
            raise AssemblyError(
                "No generated audio maps to a compiled speech segment",
                context={"segment_id": segment.id},
            )
        assembled[segment.id] = assemble_pcm(
            pieces,
            output_format,
            normalize_loudness=normalize_loudness,
        )
    return assembled


def _assemble_targets(
    compiled: CompiledScript,
    plan: RenderPlan,
    results: Mapping[str, GenerationResult],
    targets: Sequence[OutputTarget],
    output_format: str,
    *,
    normalize_loudness: bool,
) -> tuple[AudioAssemblyResult, ...]:
    if plan.output_mode == "single":
        return (
            assemble_audio(
                _timeline_parts(plan, results),
                output_format,
                normalize_loudness=normalize_loudness,
            ),
        )
    if plan.output_mode == "scene":
        return tuple(
            assemble_audio(
                _timeline_parts(plan, results, scene_id=target.scene_id),
                output_format,
                normalize_loudness=normalize_loudness,
            )
            for target in targets
        )
    segments = _segment_audio(
        compiled,
        plan,
        results,
        output_format,
        normalize_loudness=normalize_loudness,
    )
    return tuple(segments[target.segment_id or ""] for target in targets)


def _prepare_output_directory(
    output_dir: str | os.PathLike[str],
    *,
    audio_extension: str,
) -> Path:
    requested = Path(output_dir)
    if requested.suffix.casefold() == f".{audio_extension.casefold()}":
        raise WriteError(
            "output_dir must be a directory, not an audio filename",
            context={"output_dir": str(requested)},
        )
    try:
        requested.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise WriteError(
            "Output directory could not be created",
            context={"output_dir": str(requested)},
        ) from error
    if not requested.is_dir():
        raise WriteError(
            "Output path must be a directory",
            context={"output_dir": str(requested)},
        )
    return requested.resolve()


def _target_paths(root: Path, targets: Sequence[OutputTarget]) -> tuple[Path, ...]:
    paths = tuple(root / target.filename for target in targets)
    for path in paths:
        if path.resolve(strict=False).parent != root:
            raise WriteError(
                "Resolved output path escaped the output directory",
                context={"filename": path.name},
            )
        if path.exists() or path.is_symlink():
            raise WriteError(
                "Refusing to overwrite an existing output file",
                context={"path": str(path)},
            )
    return paths


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    """Publish one complete file atomically without replacing an existing path."""

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}-",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        with suppress(OSError):
            os.close(descriptor)
        with suppress(OSError):
            temporary.unlink()


def _write_all(paths: Sequence[Path], payloads: Sequence[bytes]) -> None:
    created: list[Path] = []
    try:
        for path, payload in zip(paths, payloads, strict=True):
            _write_bytes_exclusive(path, payload)
            created.append(path)
    except BaseException as error:
        for path in created:
            with suppress(OSError):
                path.unlink()
        if isinstance(error, (OSError, ValueError)):
            raise WriteError("Audio outputs could not be written") from error
        raise


def preflight_render_outputs(
    compiled: CompiledScript,
    plan: RenderPlan,
    output_dir: str | os.PathLike[str],
    *,
    output_format: str,
) -> OutputPreflight:
    """Create the output directory and reject collisions before chargeable work."""

    if plan.output_mode not in {"single", "scene", "segment"}:
        raise WriteError(f"Unknown render plan output mode {plan.output_mode!r}")
    targets = build_output_targets(compiled, plan.output_mode, output_format)
    root = _prepare_output_directory(
        output_dir,
        audio_extension=format_extension(output_format),
    )
    return OutputPreflight(root, targets, _target_paths(root, targets))


def write_render_outputs(
    compiled: CompiledScript,
    plan: RenderPlan,
    results: Mapping[str, GenerationResult],
    output_dir: str | os.PathLike[str],
    *,
    output_format: str,
    normalize_loudness: bool = False,
) -> OutputWriteResult:
    """Assemble and exclusively create every audio output for one render plan."""

    _validate_results(plan, results)
    preflight = preflight_render_outputs(
        compiled,
        plan,
        output_dir,
        output_format=output_format,
    )
    assembled = _assemble_targets(
        compiled,
        plan,
        results,
        preflight.targets,
        output_format,
        normalize_loudness=normalize_loudness,
    )
    _write_all(preflight.paths, tuple(item.data for item in assembled))
    artifacts = tuple(
        WrittenAudio(
            path=path,
            duration_seconds=audio.duration_seconds,
            scene_id=target.scene_id,
            segment_id=target.segment_id,
            ordinal=target.ordinal,
            speaker=target.speaker,
        )
        for path, target, audio in zip(
            preflight.paths,
            preflight.targets,
            assembled,
            strict=True,
        )
    )
    normalization = assembled[0].normalization if assembled else None
    return OutputWriteResult(
        files=preflight.paths,
        artifacts=artifacts,
        output_mode=plan.output_mode,
        output_format=output_format,
        extension=format_extension(output_format),
        normalize_loudness=normalize_loudness,
        normalization=normalization,
    )
