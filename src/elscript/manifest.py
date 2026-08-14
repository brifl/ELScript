"""Versioned, privacy-aware render manifest construction and writing."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from .audio import decode_audio
from .config import EffectiveConfig
from .domain import (
    CompiledScript,
    Diagnostic,
    MarkerEvent,
    NoteEvent,
    PauseEvent,
)
from .errors import AssemblyError, WriteError
from .output import OutputWriteResult, sanitize_filename_component
from .planner import RenderPlan
from .providers.base import (
    CharacterAlignment,
    GenerationResult,
    ProviderRequest,
    RequestKind,
    VoiceSegmentMetadata,
)
from .redaction import REDACTED, redact

MANIFEST_VERSION = "1.0"


class _ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestFile(_ManifestModel):
    path: str
    duration_seconds: float
    scene_id: str | None = None
    segment_id: str | None = None


class ManifestScene(_ManifestModel):
    id: str
    title: str | None = None
    files: tuple[str, ...] = ()
    start_seconds: float
    end_seconds: float
    duration_seconds: float


class ManifestPerformance(_ManifestModel):
    emotion: str
    intensity: float
    energy: float
    pace: str
    volume: str
    delivery: tuple[str, ...]
    accent: str | None = None


class ManifestSegment(_ManifestModel):
    id: str
    scene_id: str
    ordinal: int
    speaker: str
    voice_id: str
    model: str
    source_text: str | None = None
    effective_performance: ManifestPerformance
    file: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None
    file_start_seconds: float | None = None
    file_end_seconds: float | None = None
    render_request_ids: tuple[str, ...] = ()
    provider_request_ids: tuple[str, ...] = ()
    render_fingerprint: str | None = None


class ManifestProviderRequest(_ManifestModel):
    id: str
    provider_request_id: str | None = None
    kind: str
    scene_id: str
    model: str
    output_format: str
    segment_ids: tuple[str, ...]
    character_count: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    cache_status: str


class ManifestTimelineEvent(_ManifestModel):
    sequence: int
    type: Literal["speech", "pause", "marker", "note"]
    scene_id: str
    time_seconds: float
    end_seconds: float | None = None
    segment_id: str | None = None
    ordinal: int | None = None
    speaker: str | None = None
    duration_seconds: float | None = None
    after_ordinal: int | None = None
    name: str | None = None
    text: str | None = None


class ManifestAlignment(_ManifestModel):
    request_id: str
    provider_request_id: str | None = None
    kind: Literal["character", "normalized"]
    segment_id: str | None = None
    file: str | None = None
    characters: tuple[str, ...]
    timeline_start_seconds: tuple[float, ...]
    timeline_end_seconds: tuple[float, ...]
    file_start_seconds: tuple[float, ...] | None = None
    file_end_seconds: tuple[float, ...] | None = None


class ManifestVoiceSegment(_ManifestModel):
    request_id: str
    provider_request_id: str | None = None
    segment_id: str
    voice_id: str
    dialogue_input_index: int
    file: str | None = None
    timeline_start_seconds: float
    timeline_end_seconds: float
    file_start_seconds: float | None = None
    file_end_seconds: float | None = None
    character_start_index: int | None = None
    character_end_index: int | None = None


class ManifestWarning(_ManifestModel):
    code: str
    message: str
    severity: str
    phase: str
    source: str | None = None
    yaml_path: str | None = None
    context: Mapping[str, Any] = Field(default_factory=dict)


class RenderManifest(_ManifestModel):
    manifest_version: str = MANIFEST_VERSION
    elscript_version: str = "1.0"
    script_id: str
    provider: str
    models: tuple[str, ...]
    output_mode: str
    output_format: str
    duration_seconds: float
    effective_settings: Mapping[str, Any]
    files: tuple[ManifestFile, ...]
    scenes: tuple[ManifestScene, ...]
    timeline: tuple[ManifestTimelineEvent, ...]
    segments: tuple[ManifestSegment, ...]
    provider_requests: tuple[ManifestProviderRequest, ...]
    alignments: tuple[ManifestAlignment, ...] = ()
    voice_segments: tuple[ManifestVoiceSegment, ...] = ()
    warnings: tuple[ManifestWarning, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            redact(self.model_dump(mode="json", exclude_none=True)),
        )

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(),
            indent=indent,
            sort_keys=True,
            separators=None if indent is not None else (",", ":"),
        )


def _scrub_values(value: Any, forbidden_values: Sequence[str]) -> Any:
    if isinstance(value, str):
        for forbidden in forbidden_values:
            if forbidden:
                value = value.replace(forbidden, REDACTED)
        return value
    if isinstance(value, Mapping):
        return {str(key): _scrub_values(child, forbidden_values) for key, child in value.items()}
    if isinstance(value, tuple):
        return tuple(_scrub_values(child, forbidden_values) for child in value)
    if isinstance(value, list):
        return [_scrub_values(child, forbidden_values) for child in value]
    return value


@dataclass(frozen=True, slots=True)
class _RequestTiming:
    request: ProviderRequest
    start_seconds: float
    end_seconds: float
    scene_start_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(slots=True)
class _PartTiming:
    request_id: str
    part_index: int
    segment_id: str
    local_start_seconds: float | None
    local_end_seconds: float | None
    timeline_start_seconds: float | None
    timeline_end_seconds: float | None
    file: str | None = None
    file_start_seconds: float | None = None
    file_end_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class _TimelineTiming:
    event: ProviderRequest | PauseEvent | MarkerEvent | NoteEvent
    time_seconds: float
    end_seconds: float


def _provider_id(result: GenerationResult, config: EffectiveConfig) -> str | None:
    return result.request_id if config.save_request_ids else None


def _request_duration(result: GenerationResult) -> float:
    return decode_audio(result.audio, result.output_format).duration_seconds


def _timeline_timings(
    compiled: CompiledScript,
    plan: RenderPlan,
    results: Mapping[str, GenerationResult],
) -> tuple[
    dict[str, _RequestTiming],
    tuple[_TimelineTiming, ...],
    dict[str, tuple[float, float]],
    float,
]:
    by_scene: dict[str, list[ProviderRequest | PauseEvent | MarkerEvent | NoteEvent]] = defaultdict(
        list
    )
    for event in plan.timeline:
        by_scene[event.scene_id].append(event)
    request_timings: dict[str, _RequestTiming] = {}
    events: list[_TimelineTiming] = []
    scene_timings: dict[str, tuple[float, float]] = {}
    cursor = 0.0
    for scene in compiled.scenes:
        scene_start = cursor
        for event in by_scene.get(scene.id, []):
            start = cursor
            if isinstance(event, ProviderRequest):
                cursor += _request_duration(results[event.id])
                request_timings[event.id] = _RequestTiming(
                    event,
                    start,
                    cursor,
                    scene_start,
                )
            elif isinstance(event, PauseEvent):
                cursor += event.duration_seconds
            events.append(_TimelineTiming(event, start, cursor))
        scene_timings[scene.id] = (scene_start, cursor)
    return request_timings, tuple(events), scene_timings, cursor


def _unknown_dialogue_parts(timing: _RequestTiming) -> list[_PartTiming]:
    return [
        _PartTiming(
            request_id=timing.request.id,
            part_index=index,
            segment_id=part.logical_id,
            local_start_seconds=None,
            local_end_seconds=None,
            timeline_start_seconds=None,
            timeline_end_seconds=None,
        )
        for index, part in enumerate(timing.request.parts)
    ]


def _known_dialogue_parts(
    timing: _RequestTiming,
    voice_segments: Sequence[VoiceSegmentMetadata],
) -> list[_PartTiming]:
    parts: list[_PartTiming] = []
    previous_end = 0.0
    seen: set[int] = set()
    for metadata in sorted(voice_segments, key=lambda item: item.start_seconds):
        index = metadata.part_index
        if index is None or not 0 <= index < len(timing.request.parts):
            raise AssemblyError(
                "Manifest voice metadata references an unknown dialogue input",
                context={"request_id": timing.request.id, "part_index": index},
            )
        if index in seen:
            raise AssemblyError(
                "Manifest voice metadata repeats a dialogue input",
                context={"request_id": timing.request.id, "part_index": index},
            )
        if index != len(parts):
            raise AssemblyError(
                "Manifest voice metadata does not follow dialogue input order",
                context={"request_id": timing.request.id, "part_index": index},
            )
        if (
            not math.isfinite(metadata.start_seconds)
            or not math.isfinite(metadata.end_seconds)
            or metadata.start_seconds < previous_end - 1e-6
            or metadata.start_seconds < 0
            or metadata.end_seconds < metadata.start_seconds
        ):
            raise AssemblyError(
                "Manifest voice metadata has invalid or overlapping timing",
                context={"request_id": timing.request.id, "part_index": index},
            )
        planned = timing.request.parts[index]
        if metadata.voice_id != planned.segment.voice_id:
            raise AssemblyError(
                "Manifest voice metadata does not match the planned voice",
                context={"request_id": timing.request.id, "part_index": index},
            )
        if metadata.end_seconds > timing.duration_seconds + 1e-6:
            raise AssemblyError(
                "Manifest voice metadata extends beyond provider audio",
                context={"request_id": timing.request.id, "part_index": index},
            )
        parts.append(
            _PartTiming(
                request_id=timing.request.id,
                part_index=index,
                segment_id=planned.logical_id,
                local_start_seconds=metadata.start_seconds,
                local_end_seconds=metadata.end_seconds,
                timeline_start_seconds=timing.start_seconds + metadata.start_seconds,
                timeline_end_seconds=timing.start_seconds + metadata.end_seconds,
            )
        )
        previous_end = metadata.end_seconds
        seen.add(index)
    missing = sorted(set(range(len(timing.request.parts))) - seen)
    if missing:
        raise AssemblyError(
            "Manifest voice metadata omitted dialogue inputs",
            context={"request_id": timing.request.id, "missing_part_indices": missing},
        )
    return parts


def _part_timings(
    request_timings: Mapping[str, _RequestTiming],
    results: Mapping[str, GenerationResult],
) -> list[_PartTiming]:
    parts: list[_PartTiming] = []
    for timing in request_timings.values():
        request = timing.request
        result = results[request.id]
        if request.kind is RequestKind.SPEECH:
            if len(request.parts) != 1:
                raise AssemblyError("Speech request must contain exactly one manifest part")
            parts.append(
                _PartTiming(
                    request_id=request.id,
                    part_index=0,
                    segment_id=request.parts[0].logical_id,
                    local_start_seconds=0.0,
                    local_end_seconds=timing.duration_seconds,
                    timeline_start_seconds=timing.start_seconds,
                    timeline_end_seconds=timing.end_seconds,
                )
            )
        elif result.voice_segments:
            parts.extend(_known_dialogue_parts(timing, result.voice_segments))
        else:
            parts.extend(_unknown_dialogue_parts(timing))
    return parts


def _artifact_maps(
    outputs: OutputWriteResult,
) -> tuple[dict[str, str], dict[str, str], str | None]:
    scenes: dict[str, str] = {}
    segments: dict[str, str] = {}
    single: str | None = None
    for artifact in outputs.artifacts:
        name = artifact.path.name
        if artifact.segment_id is not None:
            segments[artifact.segment_id] = name
        elif artifact.scene_id is not None:
            scenes[artifact.scene_id] = name
        else:
            single = name
    return scenes, segments, single


def _attribute_files(
    part_timings: Sequence[_PartTiming],
    request_timings: Mapping[str, _RequestTiming],
    outputs: OutputWriteResult,
) -> None:
    scene_files, segment_files, single_file = _artifact_maps(outputs)
    segment_offsets: dict[str, float] = defaultdict(float)
    for part in part_timings:
        request = request_timings[part.request_id]
        if outputs.output_mode == "single":
            part.file = single_file
            part.file_start_seconds = part.timeline_start_seconds
            part.file_end_seconds = part.timeline_end_seconds
        elif outputs.output_mode == "scene":
            part.file = scene_files.get(request.request.scene_id)
            if part.timeline_start_seconds is not None:
                part.file_start_seconds = part.timeline_start_seconds - request.scene_start_seconds
            if part.timeline_end_seconds is not None:
                part.file_end_seconds = part.timeline_end_seconds - request.scene_start_seconds
        else:
            part.file = segment_files.get(part.segment_id)
            if part.local_start_seconds is not None and part.local_end_seconds is not None:
                duration = part.local_end_seconds - part.local_start_seconds
                part.file_start_seconds = segment_offsets[part.segment_id]
                part.file_end_seconds = part.file_start_seconds + duration
                segment_offsets[part.segment_id] += duration


def _manifest_files(outputs: OutputWriteResult) -> tuple[ManifestFile, ...]:
    return tuple(
        ManifestFile(
            path=artifact.path.name,
            duration_seconds=artifact.duration_seconds,
            scene_id=artifact.scene_id,
            segment_id=artifact.segment_id,
        )
        for artifact in outputs.artifacts
    )


def _manifest_scenes(
    compiled: CompiledScript,
    outputs: OutputWriteResult,
    scene_timings: Mapping[str, tuple[float, float]],
) -> tuple[ManifestScene, ...]:
    scene_files, segment_files, single_file = _artifact_maps(outputs)
    records: list[ManifestScene] = []
    for scene in compiled.scenes:
        start, end = scene_timings[scene.id]
        files: tuple[str, ...]
        if outputs.output_mode == "single":
            files = (single_file,) if single_file is not None else ()
        elif outputs.output_mode == "scene":
            name = scene_files.get(scene.id)
            files = (name,) if name is not None else ()
        else:
            files = tuple(
                segment_files[segment.id]
                for segment in compiled.segments
                if segment.scene_id == scene.id and segment.id in segment_files
            )
        records.append(
            ManifestScene(
                id=scene.id,
                title=scene.title,
                files=files,
                start_seconds=start,
                end_seconds=end,
                duration_seconds=end - start,
            )
        )
    return tuple(records)


def _manifest_requests(
    request_timings: Mapping[str, _RequestTiming],
    results: Mapping[str, GenerationResult],
    config: EffectiveConfig,
    cache_statuses: Mapping[str, str],
) -> tuple[ManifestProviderRequest, ...]:
    return tuple(
        ManifestProviderRequest(
            id=timing.request.id,
            provider_request_id=_provider_id(results[timing.request.id], config),
            kind=timing.request.kind.value,
            scene_id=timing.request.scene_id,
            model=timing.request.model,
            output_format=timing.request.output_format,
            segment_ids=tuple(dict.fromkeys(part.logical_id for part in timing.request.parts)),
            character_count=timing.request.character_count,
            start_seconds=timing.start_seconds,
            end_seconds=timing.end_seconds,
            duration_seconds=timing.duration_seconds,
            cache_status=cache_statuses.get(timing.request.id, "not_configured"),
        )
        for timing in request_timings.values()
    )


def _manifest_segments(
    compiled: CompiledScript,
    part_timings: Sequence[_PartTiming],
    outputs: OutputWriteResult,
    results: Mapping[str, GenerationResult],
    config: EffectiveConfig,
    render_fingerprints: Mapping[str, str],
) -> tuple[ManifestSegment, ...]:
    by_segment: dict[str, list[_PartTiming]] = defaultdict(list)
    for part in part_timings:
        by_segment[part.segment_id].append(part)
    artifact_duration = {
        artifact.segment_id: artifact.duration_seconds
        for artifact in outputs.artifacts
        if artifact.segment_id is not None
    }
    records: list[ManifestSegment] = []
    for segment in compiled.segments:
        timings = by_segment.get(segment.id, [])
        known = bool(timings) and all(
            part.timeline_start_seconds is not None and part.timeline_end_seconds is not None
            for part in timings
        )
        request_ids = tuple(dict.fromkeys(part.request_id for part in timings))
        provider_ids = tuple(
            provider_id
            for request_id in request_ids
            if (provider_id := _provider_id(results[request_id], config)) is not None
        )
        start = min(
            (
                part.timeline_start_seconds
                for part in timings
                if part.timeline_start_seconds is not None
            ),
            default=None,
        )
        end = max(
            (
                part.timeline_end_seconds
                for part in timings
                if part.timeline_end_seconds is not None
            ),
            default=None,
        )
        duration = (
            sum(
                (part.timeline_end_seconds or 0) - (part.timeline_start_seconds or 0)
                for part in timings
            )
            if known
            else None
        )
        file = next((part.file for part in timings if part.file is not None), None)
        file_start = next(
            (part.file_start_seconds for part in timings if part.file_start_seconds is not None),
            None,
        )
        file_end = max(
            (part.file_end_seconds for part in timings if part.file_end_seconds is not None),
            default=None,
        )
        if outputs.output_mode == "segment":
            duration = artifact_duration.get(segment.id, duration)
            file_start = 0.0 if file is not None else None
            file_end = duration if file is not None else None
        records.append(
            ManifestSegment(
                id=segment.id,
                scene_id=segment.scene_id,
                ordinal=segment.ordinal,
                speaker=segment.speaker,
                voice_id=segment.voice_id,
                model=segment.model,
                source_text=segment.text if config.include_source_text else None,
                effective_performance=ManifestPerformance(**asdict(segment.performance)),
                file=file,
                start_seconds=start if known else None,
                end_seconds=end if known else None,
                duration_seconds=duration,
                file_start_seconds=file_start if known else None,
                file_end_seconds=file_end if known else None,
                render_request_ids=request_ids,
                provider_request_ids=provider_ids,
                render_fingerprint=render_fingerprints.get(segment.id),
            )
        )
    return tuple(records)


def _timeline_records(
    event_timings: Sequence[_TimelineTiming],
    part_timings: Sequence[_PartTiming],
    compiled: CompiledScript,
    *,
    include_source_text: bool,
) -> tuple[ManifestTimelineEvent, ...]:
    by_request: dict[str, list[_PartTiming]] = defaultdict(list)
    for part in part_timings:
        by_request[part.request_id].append(part)
    segments = {segment.id: segment for segment in compiled.segments}
    records: list[ManifestTimelineEvent] = []
    for timed in event_timings:
        event = timed.event
        if isinstance(event, ProviderRequest):
            seen: set[str] = set()
            for part in by_request[event.id]:
                if part.segment_id in seen:
                    continue
                seen.add(part.segment_id)
                segment = segments[part.segment_id]
                related = [
                    item for item in by_request[event.id] if item.segment_id == part.segment_id
                ]
                starts = [
                    item.timeline_start_seconds
                    for item in related
                    if item.timeline_start_seconds is not None
                ]
                ends = [
                    item.timeline_end_seconds
                    for item in related
                    if item.timeline_end_seconds is not None
                ]
                records.append(
                    ManifestTimelineEvent(
                        sequence=len(records) + 1,
                        type="speech",
                        scene_id=event.scene_id,
                        time_seconds=min(starts, default=timed.time_seconds),
                        end_seconds=max(ends) if ends else None,
                        segment_id=segment.id,
                        ordinal=segment.ordinal,
                        speaker=segment.speaker,
                    )
                )
        elif isinstance(event, PauseEvent):
            records.append(
                ManifestTimelineEvent(
                    sequence=len(records) + 1,
                    type="pause",
                    scene_id=event.scene_id,
                    time_seconds=timed.time_seconds,
                    end_seconds=timed.end_seconds,
                    duration_seconds=event.duration_seconds,
                    after_ordinal=event.after_ordinal,
                )
            )
        elif isinstance(event, MarkerEvent):
            records.append(
                ManifestTimelineEvent(
                    sequence=len(records) + 1,
                    type="marker",
                    scene_id=event.scene_id,
                    time_seconds=timed.time_seconds,
                    after_ordinal=event.after_ordinal,
                    name=event.name,
                )
            )
        else:
            records.append(
                ManifestTimelineEvent(
                    sequence=len(records) + 1,
                    type="note",
                    scene_id=event.scene_id,
                    time_seconds=timed.time_seconds,
                    after_ordinal=event.after_ordinal,
                    text=event.text if include_source_text else None,
                )
            )
    return tuple(records)


def _alignment_record(
    alignment: CharacterAlignment,
    *,
    kind: Literal["character", "normalized"],
    timing: _RequestTiming,
    result: GenerationResult,
    config: EffectiveConfig,
    part: _PartTiming,
) -> ManifestAlignment | None:
    assert part.local_start_seconds is not None
    assert part.local_end_seconds is not None
    indices = tuple(
        index
        for index, (start, end) in enumerate(
            zip(alignment.start_seconds, alignment.end_seconds, strict=True)
        )
        if start >= part.local_start_seconds - 1e-6 and end <= part.local_end_seconds + 1e-6
    )
    if not indices:
        return None
    file = part.file
    assert part.file_start_seconds is not None
    file_offset = part.file_start_seconds - part.local_start_seconds
    selected = tuple(indices)
    starts = tuple(alignment.start_seconds[index] for index in selected)
    ends = tuple(alignment.end_seconds[index] for index in selected)
    timeline_starts = tuple(timing.start_seconds + value for value in starts)
    timeline_ends = tuple(timing.start_seconds + value for value in ends)
    return ManifestAlignment(
        request_id=timing.request.id,
        provider_request_id=_provider_id(result, config),
        kind=kind,
        segment_id=part.segment_id,
        file=file,
        characters=tuple(alignment.characters[index] for index in selected),
        timeline_start_seconds=timeline_starts,
        timeline_end_seconds=timeline_ends,
        file_start_seconds=tuple(value + file_offset for value in starts),
        file_end_seconds=tuple(value + file_offset for value in ends),
    )


def _validate_alignment(
    alignment: CharacterAlignment,
    *,
    request_id: str,
    duration_seconds: float,
) -> None:
    lengths = {
        len(alignment.characters),
        len(alignment.start_seconds),
        len(alignment.end_seconds),
    }
    if len(lengths) != 1:
        raise AssemblyError(
            "Manifest character alignment arrays have different lengths",
            context={"request_id": request_id},
        )
    previous_end = 0.0
    for index, (start, end) in enumerate(
        zip(alignment.start_seconds, alignment.end_seconds, strict=True)
    ):
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < previous_end - 1e-6
            or start < 0
            or end < start
            or end > duration_seconds + 1e-6
        ):
            raise AssemblyError(
                "Manifest character alignment has invalid or overlapping timing",
                context={"request_id": request_id, "character_index": index},
            )
        previous_end = end


def _manifest_alignments(
    request_timings: Mapping[str, _RequestTiming],
    part_timings: Sequence[_PartTiming],
    results: Mapping[str, GenerationResult],
    outputs: OutputWriteResult,
    config: EffectiveConfig,
) -> tuple[ManifestAlignment, ...]:
    by_request: dict[str, list[_PartTiming]] = defaultdict(list)
    for part in part_timings:
        by_request[part.request_id].append(part)
    records: list[ManifestAlignment] = []
    scene_files, _, single_file = _artifact_maps(outputs)
    for request_id, timing in request_timings.items():
        result = results[request_id]
        candidates: list[tuple[Literal["character", "normalized"], CharacterAlignment]] = []
        if config.save_character_timestamps and result.alignment is not None:
            candidates.append(("character", result.alignment))
        if config.save_normalized_timestamps and result.normalized_alignment is not None:
            candidates.append(("normalized", result.normalized_alignment))
        for kind, alignment in candidates:
            _validate_alignment(
                alignment,
                request_id=request_id,
                duration_seconds=timing.duration_seconds,
            )
            if outputs.output_mode == "segment":
                for part in by_request[request_id]:
                    if part.local_start_seconds is None:
                        continue
                    record = _alignment_record(
                        alignment,
                        kind=kind,
                        timing=timing,
                        result=result,
                        config=config,
                        part=part,
                    )
                    if record is not None:
                        records.append(record)
            else:
                starts = tuple(timing.start_seconds + value for value in alignment.start_seconds)
                ends = tuple(timing.start_seconds + value for value in alignment.end_seconds)
                offset = 0.0 if outputs.output_mode == "single" else -timing.scene_start_seconds
                records.append(
                    ManifestAlignment(
                        request_id=request_id,
                        provider_request_id=_provider_id(result, config),
                        kind=kind,
                        file=(
                            single_file
                            if outputs.output_mode == "single"
                            else scene_files.get(timing.request.scene_id)
                        ),
                        characters=alignment.characters,
                        timeline_start_seconds=starts,
                        timeline_end_seconds=ends,
                        file_start_seconds=tuple(
                            timing.start_seconds + value + offset
                            for value in alignment.start_seconds
                        ),
                        file_end_seconds=tuple(
                            timing.start_seconds + value + offset for value in alignment.end_seconds
                        ),
                    )
                )
    return tuple(records)


def _manifest_voice_segments(
    request_timings: Mapping[str, _RequestTiming],
    part_timings: Sequence[_PartTiming],
    results: Mapping[str, GenerationResult],
    config: EffectiveConfig,
) -> tuple[ManifestVoiceSegment, ...]:
    if not config.save_voice_segments:
        return ()
    by_key = {
        (part.request_id, part.part_index, part.local_start_seconds, part.local_end_seconds): part
        for part in part_timings
    }
    records: list[ManifestVoiceSegment] = []
    for request_id, timing in request_timings.items():
        result = results[request_id]
        for metadata in result.voice_segments:
            if metadata.part_index is None:
                continue
            part = by_key.get(
                (
                    request_id,
                    metadata.part_index,
                    metadata.start_seconds,
                    metadata.end_seconds,
                )
            )
            if part is None:
                raise AssemblyError(
                    "Voice metadata could not be attributed in the manifest",
                    context={"request_id": request_id, "part_index": metadata.part_index},
                )
            records.append(
                ManifestVoiceSegment(
                    request_id=request_id,
                    provider_request_id=_provider_id(result, config),
                    segment_id=part.segment_id,
                    voice_id=metadata.voice_id,
                    dialogue_input_index=metadata.part_index,
                    file=part.file,
                    timeline_start_seconds=timing.start_seconds + metadata.start_seconds,
                    timeline_end_seconds=timing.start_seconds + metadata.end_seconds,
                    file_start_seconds=part.file_start_seconds,
                    file_end_seconds=part.file_end_seconds,
                    character_start_index=metadata.character_start_index,
                    character_end_index=metadata.character_end_index,
                )
            )
    return tuple(records)


def _manifest_warnings(warnings: Sequence[Diagnostic]) -> tuple[ManifestWarning, ...]:
    return tuple(
        ManifestWarning(
            code=warning.code,
            message=warning.message,
            severity=warning.severity.value,
            phase=warning.phase.value,
            source=warning.location.source if warning.location is not None else None,
            yaml_path=warning.location.yaml_path if warning.location is not None else None,
            context=redact(warning.context),
        )
        for warning in warnings
    )


def build_manifest(
    compiled: CompiledScript,
    plan: RenderPlan,
    results: Mapping[str, GenerationResult],
    outputs: OutputWriteResult,
    config: EffectiveConfig,
    *,
    warnings: Sequence[Diagnostic] = (),
    cache_statuses: Mapping[str, str] | None = None,
    render_fingerprints: Mapping[str, str] | None = None,
) -> RenderManifest:
    """Build a deterministic manifest from the exact plan, results, and files."""

    expected = {request.id for request in plan.requests}
    if set(results) != expected:
        raise AssemblyError("Manifest results do not match the render plan")
    if outputs.output_mode != plan.output_mode or outputs.output_format != config.output_format:
        raise AssemblyError("Manifest inputs disagree about effective output settings")
    request_timings, events, scene_timings, duration = _timeline_timings(
        compiled,
        plan,
        results,
    )
    parts = _part_timings(request_timings, results)
    _attribute_files(parts, request_timings, outputs)
    cache = {} if cache_statuses is None else dict(cache_statuses)
    fingerprints = {} if render_fingerprints is None else dict(render_fingerprints)
    settings = config.to_public_dict()
    settings["normalization"] = outputs.normalization
    manifest = RenderManifest(
        script_id=compiled.script_id,
        provider=plan.provider_id,
        models=tuple(dict.fromkeys(request.model for request in plan.requests)),
        output_mode=outputs.output_mode,
        output_format=outputs.output_format,
        duration_seconds=duration,
        effective_settings=redact(settings),
        files=_manifest_files(outputs),
        scenes=_manifest_scenes(compiled, outputs, scene_timings),
        timeline=_timeline_records(
            events,
            parts,
            compiled,
            include_source_text=config.include_source_text,
        ),
        segments=_manifest_segments(
            compiled,
            parts,
            outputs,
            results,
            config,
            fingerprints,
        ),
        provider_requests=_manifest_requests(
            request_timings,
            results,
            config,
            cache,
        ),
        alignments=_manifest_alignments(
            request_timings,
            parts,
            results,
            outputs,
            config,
        ),
        voice_segments=_manifest_voice_segments(
            request_timings,
            parts,
            results,
            config,
        ),
        warnings=_manifest_warnings(warnings),
    )
    secret_values = (config.credential.reveal(),) if config.credential is not None else ()
    if not secret_values:
        return manifest
    safe_payload = _scrub_values(manifest.to_dict(), secret_values)
    return RenderManifest.model_validate(safe_payload)


def write_manifest(
    manifest: RenderManifest,
    output_dir: str | os.PathLike[str],
) -> Path:
    """Exclusively write a deterministic UTF-8 JSON manifest beside audio files."""

    path = preflight_manifest_output(manifest.script_id, output_dir)
    payload = f"{manifest.to_json()}\n"
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as output:
            created = True
            output.write(payload)
    except FileExistsError as error:
        raise WriteError(
            "Refusing to overwrite an existing manifest",
            context={"path": str(path)},
        ) from error
    except OSError as error:
        if created:
            with suppress(OSError):
                path.unlink()
        raise WriteError("Manifest could not be written") from error
    return path


def preflight_manifest_output(
    script_id: str,
    output_dir: str | os.PathLike[str],
) -> Path:
    """Resolve a contained manifest path and reject an existing destination."""

    root = Path(output_dir).resolve()
    if not root.is_dir():
        raise WriteError("Manifest output directory does not exist")
    path = root / f"{sanitize_filename_component(script_id)}.manifest.json"
    if path.resolve(strict=False).parent != root:
        raise WriteError("Resolved manifest path escaped the output directory")
    if path.exists() or path.is_symlink():
        raise WriteError(
            "Refusing to overwrite an existing manifest",
            context={"path": str(path)},
        )
    return path
