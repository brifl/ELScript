"""Ordered provider-stream normalization into public attributed chunks."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from typing import Any

from .audio import decode_audio, encode_audio, slice_audio
from .domain import AudioChunk, MarkerEvent, NoteEvent, PauseEvent
from .errors import ELScriptError, GenerationError
from .planner import RenderPlan
from .providers.base import (
    GenerationChunk,
    Provider,
    ProviderRequest,
    RequestKind,
    VoiceSegmentMetadata,
    request_diagnostic_context,
)


def _close(iterator: Iterator[GenerationChunk]) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        close()


def _provider_chunks(
    provider: Provider,
    request: ProviderRequest,
) -> Iterator[GenerationChunk]:
    try:
        iterator = provider.stream(request)
        try:
            yield from iterator
        finally:
            _close(iterator)
    except ELScriptError as error:
        error.enrich_context(request_diagnostic_context(provider.provider_id, request))
        raise
    except Exception as error:
        raise GenerationError(
            "Provider streaming failed unexpectedly",
            context=request_diagnostic_context(provider.provider_id, request),
        ) from error


def _chunk_metadata(chunk: GenerationChunk, request: ProviderRequest) -> dict[str, Any]:
    metadata = dict(chunk.metadata)
    metadata.update(
        {
            "render_request_id": request.id,
            "provider_request_id": chunk.request_id,
        }
    )
    if chunk.alignment is not None:
        metadata["alignment"] = chunk.alignment
    if chunk.normalized_alignment is not None:
        metadata["normalized_alignment"] = chunk.normalized_alignment
    if chunk.voice_segments:
        metadata["voice_segments"] = chunk.voice_segments
    return metadata


def _speech_chunks(
    request: ProviderRequest,
    provider: Provider,
    last_request_by_segment: Mapping[str, str],
) -> Iterator[AudioChunk]:
    if len(request.parts) != 1:
        raise GenerationError(
            "A streamed speech request must contain exactly one part",
            context={"request_id": request.id},
        )
    segment = request.parts[0].segment
    emitted = False
    final_seen = False
    provider_request_id: str | None = None
    for chunk in _provider_chunks(provider, request):
        if chunk.output_format != request.output_format:
            raise GenerationError(
                "Provider stream format does not match the planned request",
                context={"request_id": request.id},
            )
        if final_seen:
            raise GenerationError(
                "Provider emitted audio after the final stream chunk",
                context={"request_id": request.id},
            )
        if (
            provider_request_id is not None
            and chunk.request_id is not None
            and chunk.request_id != provider_request_id
        ):
            raise GenerationError(
                "Provider request ID changed within one stream",
                context={"request_id": request.id},
            )
        provider_request_id = chunk.request_id or provider_request_id
        final_seen = chunk.final
        if not chunk.audio:
            continue
        emitted = True
        yield AudioChunk(
            data=chunk.audio,
            format=chunk.output_format,
            scene_id=request.scene_id,
            segment_id=segment.id,
            ordinal=segment.ordinal,
            speaker=segment.speaker,
            final_for_segment=(chunk.final and last_request_by_segment[segment.id] == request.id),
            metadata=_chunk_metadata(chunk, request),
        )
    if not emitted or not final_seen:
        raise GenerationError(
            "Provider stream ended without a final audio chunk",
            context={"request_id": request.id},
        )


def _dialogue_result(
    request: ProviderRequest,
    provider: Provider,
) -> tuple[bytes, tuple[VoiceSegmentMetadata, ...], str | None, Mapping[str, Any]]:
    audio: list[bytes] = []
    voice_segments: list[VoiceSegmentMetadata] = []
    metadata: dict[str, Any] = {}
    provider_request_id: str | None = None
    final_seen = False
    for chunk in _provider_chunks(provider, request):
        if chunk.output_format != request.output_format:
            raise GenerationError(
                "Provider stream format does not match the planned request",
                context={"request_id": request.id},
            )
        if final_seen:
            raise GenerationError(
                "Provider emitted audio after the final stream chunk",
                context={"request_id": request.id},
            )
        if (
            provider_request_id is not None
            and chunk.request_id is not None
            and chunk.request_id != provider_request_id
        ):
            raise GenerationError(
                "Provider request ID changed within one stream",
                context={"request_id": request.id},
            )
        provider_request_id = chunk.request_id or provider_request_id
        final_seen = chunk.final
        audio.append(chunk.audio)
        voice_segments.extend(chunk.voice_segments)
        metadata.update(chunk.metadata)
    if not any(audio) or not final_seen:
        raise GenerationError(
            "Provider stream ended without a final audio chunk",
            context={"request_id": request.id},
        )
    return b"".join(audio), tuple(voice_segments), provider_request_id, metadata


def _dialogue_chunks(
    request: ProviderRequest,
    provider: Provider,
    last_request_by_segment: Mapping[str, str],
) -> Iterator[AudioChunk]:
    audio, voice_segments, provider_request_id, provider_metadata = _dialogue_result(
        request,
        provider,
    )
    try:
        decoded = decode_audio(audio, request.output_format)
    except ELScriptError as error:
        error.enrich_context(
            request_diagnostic_context(
                provider.provider_id,
                request,
                provider_request_id=provider_request_id,
            )
        )
        raise
    ordered = sorted(voice_segments, key=lambda item: item.start_seconds)
    if len(ordered) != len(request.parts):
        raise GenerationError(
            "Dialogue stream metadata does not cover every planned input",
            context={"request_id": request.id},
        )
    previous_end = 0.0
    for expected_index, voice in enumerate(ordered):
        index = voice.part_index
        if index != expected_index:
            raise GenerationError(
                "Dialogue stream metadata does not follow authored input order",
                context={"request_id": request.id, "part_index": index},
            )
        part = request.parts[index]
        if voice.voice_id != part.segment.voice_id:
            raise GenerationError(
                "Dialogue stream metadata does not match the planned voice",
                context={"request_id": request.id, "part_index": index},
            )
        if (
            not math.isfinite(voice.start_seconds)
            or not math.isfinite(voice.end_seconds)
            or voice.start_seconds < 0
            or voice.start_seconds < previous_end - (1 / decoded.sample_rate)
            or voice.end_seconds <= voice.start_seconds
            or voice.end_seconds > decoded.duration_seconds + (1 / decoded.sample_rate)
        ):
            raise GenerationError(
                "Dialogue stream contains invalid or overlapping voice timing",
                context={"request_id": request.id, "part_index": index},
            )
        encoded = encode_audio(
            slice_audio(decoded, voice.start_seconds, voice.end_seconds),
            request.output_format,
        )
        yield AudioChunk(
            data=encoded.data,
            format=request.output_format,
            scene_id=request.scene_id,
            segment_id=part.segment.id,
            ordinal=part.segment.ordinal,
            speaker=part.segment.speaker,
            final_for_segment=last_request_by_segment[part.logical_id] == request.id,
            metadata={
                **provider_metadata,
                "render_request_id": request.id,
                "provider_request_id": provider_request_id,
                "dialogue_input_index": index,
                "voice_segment": voice,
            },
        )
        previous_end = voice.end_seconds


def _event_chunk(
    event: PauseEvent | MarkerEvent | NoteEvent,
    *,
    output_format: str,
    include_source_text: bool,
) -> AudioChunk:
    metadata: dict[str, Any] = {"after_ordinal": event.after_ordinal}
    if isinstance(event, PauseEvent):
        event_type = "pause"
        metadata["duration_seconds"] = event.duration_seconds
    elif isinstance(event, MarkerEvent):
        event_type = "marker"
        metadata["name"] = event.name
    else:
        event_type = "note"
        if include_source_text:
            metadata["text"] = event.text
    return AudioChunk(
        data=b"",
        format=output_format,
        scene_id=event.scene_id,
        event=event_type,
        metadata=metadata,
    )


def stream_render_plan(
    plan: RenderPlan,
    provider: Provider,
    *,
    output_format: str,
    include_source_text: bool,
) -> Iterator[AudioChunk]:
    """Yield ordered public chunks while pulling the provider only on demand."""

    last_request_by_segment = {
        part.logical_id: request.id for request in plan.requests for part in request.parts
    }
    for event in plan.timeline:
        if not isinstance(event, ProviderRequest):
            yield _event_chunk(
                event,
                output_format=output_format,
                include_source_text=include_source_text,
            )
            continue
        try:
            if event.kind is RequestKind.SPEECH:
                yield from _speech_chunks(event, provider, last_request_by_segment)
            else:
                yield from _dialogue_chunks(event, provider, last_request_by_segment)
        except ELScriptError as error:
            error.enrich_context(request_diagnostic_context(plan.provider_id, event))
            raise
