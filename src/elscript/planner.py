"""Pure, deterministic render planning over compiled ELScript timelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .config import EffectiveConfig
from .domain import CompiledScript, MarkerEvent, NoteEvent, PauseEvent, SpeechSegment
from .errors import (
    CapabilityError,
    ProviderLimitError,
    UnsupportedModelFeatureError,
    UnsupportedOutputFormatError,
)
from .providers.base import (
    DictionaryLocator,
    EndpointCapabilities,
    PlannedSegmentPart,
    ProviderCapabilities,
    ProviderFeature,
    ProviderRequest,
    RequestKind,
)

PlanEvent = ProviderRequest | PauseEvent | MarkerEvent | NoteEvent


@dataclass(frozen=True, slots=True)
class RenderPlan:
    provider_id: str
    output_mode: str
    streaming: bool
    capability_version: str
    timeline: tuple[PlanEvent, ...]
    requests: tuple[ProviderRequest, ...]


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _canonical(child))
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (tuple, list)):
        return tuple(_canonical(child) for child in value)
    return value


def _setting(segment: SpeechSegment, name: str, default: Any = None) -> Any:
    return segment.render_settings.get(name, default)


def _compatibility_key(segment: SpeechSegment) -> tuple[Any, ...]:
    """Identify request-level values that cannot be mixed in one provider call."""

    return (
        segment.scene_id,
        segment.model,
        segment.language,
        _setting(segment, "provider"),
        _setting(segment, "render_mode", "auto"),
        _setting(segment, "output_format"),
        bool(_setting(segment, "timestamps", False)),
        _canonical(segment.render_settings),
        _canonical(segment.provider_options),
    )


def _direction_text(segment: SpeechSegment) -> str:
    return " ".join(f"[{value}]" for value in (*segment.cues, *segment.tags))


def _character_count(part: PlannedSegmentPart) -> int:
    directions = _direction_text(part.segment)
    if part.text is None:
        return len(directions)
    return len(part.text) + len(directions) + (1 if directions else 0)


def _split_text(text: str, max_chars: int) -> tuple[str, ...]:
    """Split without losing characters, preferring the last whitespace boundary."""

    if len(text) <= max_chars:
        return (text,)
    parts: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        boundary = max(
            (index for index, value in enumerate(remaining[:max_chars]) if value.isspace()),
            default=-1,
        )
        cut = boundary + 1 if boundary > 0 else max_chars
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        parts.append(remaining)
    return tuple(parts)


def _parts_for_segment(
    segment: SpeechSegment,
    *,
    request_limit: int,
) -> tuple[PlannedSegmentPart, ...]:
    direction_chars = len(_direction_text(segment))
    if segment.text is not None and direction_chars:
        direction_chars += 1
    text_budget = request_limit - direction_chars
    if segment.text is None:
        if direction_chars > request_limit:
            raise ProviderLimitError(
                f"Segment {segment.id!r} directions exceed the provider request limit",
                context={"segment_id": segment.id, "limit": request_limit},
            )
        texts: tuple[str | None, ...] = (None,)
    else:
        if text_budget < 1:
            raise ProviderLimitError(
                f"Segment {segment.id!r} directions leave no room for speech text",
                context={"segment_id": segment.id, "limit": request_limit},
            )
        texts = _split_text(segment.text, text_budget)
    part_count = len(texts)
    return tuple(
        PlannedSegmentPart(
            segment=segment,
            text=text,
            part_index=index,
            part_count=part_count,
        )
        for index, text in enumerate(texts, start=1)
    )


def _request_limit(config: EffectiveConfig, endpoint: EndpointCapabilities) -> int:
    limits = [config.chunking.max_chars]
    if endpoint.recommended_request_chars is not None:
        limits.append(endpoint.recommended_request_chars)
    if endpoint.hard_request_chars is not None:
        limits.append(endpoint.hard_request_chars)
    return min(limits)


def _capability_error(
    endpoint: EndpointCapabilities,
    *,
    kind: RequestKind,
    segment: SpeechSegment,
    config: EffectiveConfig,
    streaming: bool,
    dictionaries: Sequence[DictionaryLocator],
) -> CapabilityError | None:
    model = segment.model
    output_format = str(_setting(segment, "output_format", config.output_format))
    if endpoint.supported_models is not None and model not in endpoint.supported_models:
        return UnsupportedModelFeatureError(
            f"Model {model!r} does not support {kind.value} requests",
            context={"model": model, "mode": kind.value, "segment_id": segment.id},
        )
    if (
        endpoint.supported_output_formats is not None
        and output_format not in endpoint.supported_output_formats
    ):
        return UnsupportedOutputFormatError(
            f"Output format {output_format!r} is not supported for {kind.value} requests",
            context={"output_format": output_format, "mode": kind.value},
        )
    if streaming and not endpoint.supports(ProviderFeature.STREAMING):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests do not support streaming",
            context={"mode": kind.value, "segment_id": segment.id},
        )

    timestamps = bool(_setting(segment, "timestamps", config.timestamps))
    dialogue_attribution = kind is RequestKind.DIALOGUE and (
        streaming or config.output_mode == "segment"
    )
    if (timestamps or dialogue_attribution) and not endpoint.supports(ProviderFeature.TIMESTAMPS):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests cannot provide required timestamps",
            context={"mode": kind.value, "segment_id": segment.id},
        )
    if dialogue_attribution and not endpoint.supports(ProviderFeature.SPEAKER_SEGMENTS):
        return UnsupportedModelFeatureError(
            "Dialogue output cannot be attributed to authored segments",
            context={"output_mode": config.output_mode, "segment_id": segment.id},
        )
    if dictionaries and not endpoint.supports(ProviderFeature.PRONUNCIATION_DICTIONARIES):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests do not support pronunciation dictionaries",
            context={"dictionary_count": len(dictionaries), "mode": kind.value},
        )
    if len(dictionaries) > endpoint.max_pronunciation_dictionaries:
        return ProviderLimitError(
            f"{kind.value} requests support at most "
            f"{endpoint.max_pronunciation_dictionaries} pronunciation dictionaries",
            context={
                "dictionary_count": len(dictionaries),
                "limit": endpoint.max_pronunciation_dictionaries,
            },
        )
    if _setting(segment, "seed", config.seed) is not None and not endpoint.supports(
        ProviderFeature.SEED
    ):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests do not support a generation seed",
            context={"mode": kind.value, "segment_id": segment.id},
        )
    if (
        _setting(segment, "text_normalization", config.text_normalization) != "auto"
        and not endpoint.supports(ProviderFeature.TEXT_NORMALIZATION)
    ):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests do not support text normalization control",
            context={"mode": kind.value, "segment_id": segment.id},
        )
    if bool(
        _setting(
            segment,
            "language_text_normalization",
            config.language_text_normalization,
        )
    ) and not endpoint.supports(ProviderFeature.LANGUAGE_NORMALIZATION):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests do not support language normalization",
            context={"mode": kind.value, "segment_id": segment.id},
        )
    if not bool(
        _setting(segment, "enable_logging", config.enable_logging)
    ) and not endpoint.supports(ProviderFeature.REQUEST_LOGGING_CONTROL):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests cannot disable provider request logging",
            context={"mode": kind.value, "segment_id": segment.id},
        )
    return None


def _endpoint_for_run(
    segments: Sequence[SpeechSegment],
    *,
    config: EffectiveConfig,
    capabilities: ProviderCapabilities,
    streaming: bool,
    dictionaries: Sequence[DictionaryLocator],
) -> tuple[RequestKind, EndpointCapabilities]:
    requested_mode = str(_setting(segments[0], "render_mode", config.render_mode))
    if requested_mode not in {"auto", "speech", "dialogue"}:
        raise CapabilityError(f"Unknown render mode {requested_mode!r}")

    def candidate(kind: RequestKind) -> tuple[EndpointCapabilities | None, CapabilityError | None]:
        endpoint = capabilities.for_kind(kind)
        if endpoint is None:
            return None, UnsupportedModelFeatureError(
                f"Provider {capabilities.provider_id!r} has no {kind.value} endpoint",
                context={"provider": capabilities.provider_id, "mode": kind.value},
            )
        for segment in segments:
            error = _capability_error(
                endpoint,
                kind=kind,
                segment=segment,
                config=config,
                streaming=streaming,
                dictionaries=dictionaries,
            )
            if error is not None:
                return endpoint, error
        return endpoint, None

    if requested_mode != "auto":
        kind = RequestKind(requested_mode)
        endpoint, error = candidate(kind)
        if error is not None:
            raise error
        assert endpoint is not None
        return kind, endpoint

    should_try_dialogue = len(segments) > 1 and len({item.speaker for item in segments}) > 1
    if should_try_dialogue:
        dialogue, dialogue_error = candidate(RequestKind.DIALOGUE)
        if dialogue is not None and dialogue_error is None:
            return RequestKind.DIALOGUE, dialogue

    speech, speech_error = candidate(RequestKind.SPEECH)
    if speech_error is not None:
        raise speech_error
    assert speech is not None
    return RequestKind.SPEECH, speech


@dataclass(frozen=True, slots=True)
class _RequestDraft:
    kind: RequestKind
    parts: tuple[PlannedSegmentPart, ...]
    character_count: int
    timestamps: bool


def _request_drafts(
    segments: Sequence[SpeechSegment],
    *,
    kind: RequestKind,
    endpoint: EndpointCapabilities,
    config: EffectiveConfig,
    streaming: bool,
) -> tuple[_RequestDraft, ...]:
    limit = _request_limit(config, endpoint)
    parts_by_segment = [
        _parts_for_segment(segment, request_limit=limit) for segment in segments
    ]
    force_timestamps = kind is RequestKind.DIALOGUE and (
        streaming or config.output_mode == "segment"
    )

    if kind is RequestKind.SPEECH:
        return tuple(
            _RequestDraft(
                kind=kind,
                parts=(part,),
                character_count=_character_count(part),
                timestamps=bool(
                    _setting(part.segment, "timestamps", config.timestamps)
                ),
            )
            for segment_parts in parts_by_segment
            for part in segment_parts
        )

    drafts: list[_RequestDraft] = []
    pending: list[PlannedSegmentPart] = []
    pending_chars = 0
    pending_voices: set[str] = set()

    def flush() -> None:
        nonlocal pending, pending_chars, pending_voices
        if not pending:
            return
        drafts.append(
            _RequestDraft(
                kind=kind,
                parts=tuple(pending),
                character_count=pending_chars,
                timestamps=force_timestamps
                or bool(_setting(pending[0].segment, "timestamps", config.timestamps)),
            )
        )
        pending = []
        pending_chars = 0
        pending_voices = set()

    for segment_parts in parts_by_segment:
        for part in segment_parts:
            part_chars = _character_count(part)
            part_voice = part.segment.voice_id
            split_part = part.part_count > 1
            if split_part:
                flush()
            exceeds_chars = bool(pending) and pending_chars + part_chars > limit
            exceeds_voices = bool(pending) and len(pending_voices | {part_voice}) > (
                endpoint.max_unique_voices
            )
            if exceeds_chars or exceeds_voices:
                flush()
            pending.append(part)
            pending_chars += part_chars
            pending_voices.add(part_voice)
            if split_part:
                flush()
    flush()
    return tuple(drafts)


def plan_render(
    compiled: CompiledScript,
    config: EffectiveConfig,
    capabilities: ProviderCapabilities,
    *,
    streaming: bool = False,
    dictionaries: Iterable[DictionaryLocator] = (),
) -> RenderPlan:
    """Create a deterministic, charge-free request plan for a compiled script."""

    if config.provider != capabilities.provider_id:
        raise CapabilityError(
            f"Resolved provider {config.provider!r} does not match capability provider "
            f"{capabilities.provider_id!r}",
            context={
                "configured_provider": config.provider,
                "capability_provider": capabilities.provider_id,
            },
        )
    dictionary_locators = tuple(dictionaries)
    timeline: list[PlanEvent] = []
    requests: list[ProviderRequest] = []
    pending: list[SpeechSegment] = []

    def flush() -> None:
        if not pending:
            return
        kind, endpoint = _endpoint_for_run(
            pending,
            config=config,
            capabilities=capabilities,
            streaming=streaming,
            dictionaries=dictionary_locators,
        )
        for draft in _request_drafts(
            pending,
            kind=kind,
            endpoint=endpoint,
            config=config,
            streaming=streaming,
        ):
            first = draft.parts[0].segment
            request = ProviderRequest(
                id=f"request.{len(requests) + 1:04d}",
                kind=draft.kind,
                scene_id=first.scene_id,
                parts=draft.parts,
                model=first.model,
                language=first.language,
                output_format=str(_setting(first, "output_format", config.output_format)),
                timestamps=draft.timestamps,
                streaming=streaming,
                character_count=draft.character_count,
                dictionary_locators=dictionary_locators,
                render_settings=first.render_settings,
                provider_options=first.provider_options,
            )
            timeline.append(request)
            requests.append(request)
        pending.clear()

    for scene in compiled.scenes:
        flush()
        for event in scene.events:
            if isinstance(event, SpeechSegment):
                configured_provider = str(_setting(event, "provider", config.provider))
                if configured_provider != capabilities.provider_id:
                    raise CapabilityError(
                        f"Scene selects provider {configured_provider!r}, but planner received "
                        f"capabilities for {capabilities.provider_id!r}",
                        context={"scene_id": event.scene_id, "segment_id": event.id},
                    )
                if pending and _compatibility_key(pending[-1]) != _compatibility_key(event):
                    flush()
                pending.append(event)
            else:
                flush()
                timeline.append(event)
        flush()

    return RenderPlan(
        provider_id=capabilities.provider_id,
        output_mode=config.output_mode,
        streaming=streaming,
        capability_version=capabilities.capability_version,
        timeline=tuple(timeline),
        requests=tuple(requests),
    )
