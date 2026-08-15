"""Pure, deterministic render planning over compiled ELScript timelines."""

from __future__ import annotations

import re
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
    PreparedSegment,
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
    if part.translation_version is not None:
        return len(part.text or "")
    directions = _direction_text(part.segment)
    if part.text is None:
        return len(directions)
    return len(part.text) + len(directions) + (1 if directions else 0)


def _split_text(
    text: str,
    max_chars: int,
    *,
    atomic_tokens: Sequence[str] = (),
) -> tuple[str, ...]:
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
        protected_ranges = [
            (match.start(), match.end())
            for token in atomic_tokens
            for match in re.finditer(re.escape(token), remaining)
        ]
        containing = next(
            ((start, end) for start, end in protected_ranges if start < cut < end),
            None,
        )
        if containing is not None:
            start, end = containing
            if start == 0:
                if end > max_chars:
                    raise ValueError("an atomic provider-text token exceeds the request limit")
                cut = end
            else:
                cut = start
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        parts.append(remaining)
    return tuple(parts)


def _parts_for_segment(
    segment: SpeechSegment,
    *,
    request_limit: int,
    prepared: PreparedSegment | None = None,
) -> tuple[PlannedSegmentPart, ...]:
    direction_text = prepared.prefix if prepared is not None else _direction_text(segment)
    direction_chars = len(direction_text)
    source_text = prepared.text if prepared is not None else segment.text
    if source_text is not None and direction_chars:
        direction_chars += 1
    text_budget = request_limit - direction_chars
    if source_text is None:
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
        try:
            texts = _split_text(
                source_text,
                text_budget,
                atomic_tokens=(prepared.atomic_tokens if prepared is not None else ()),
            )
        except ValueError as error:
            raise ProviderLimitError(
                f"Segment {segment.id!r} contains an indivisible provider token that exceeds "
                "the request limit",
                context={"segment_id": segment.id, "limit": request_limit},
            ) from error
    part_count = len(texts)
    parts: list[PlannedSegmentPart] = []
    for index, text in enumerate(texts, start=1):
        provider_text = text
        if prepared is not None:
            provider_text = " ".join(value for value in (prepared.prefix, text) if value)
        parts.append(
            PlannedSegmentPart(
                segment=segment,
                text=provider_text,
                part_index=index,
                part_count=part_count,
                translation_version=(
                    prepared.translation_version if prepared is not None else None
                ),
                features_used=(prepared.features_used if prepared is not None else frozenset()),
            )
        )
    return tuple(parts)


def _request_limit(
    config: EffectiveConfig,
    endpoint: EndpointCapabilities,
    segment: SpeechSegment,
) -> int:
    chunking = _setting(segment, "chunking", {})
    scene_max_chars = chunking.get("max_chars") if isinstance(chunking, Mapping) else None
    limits = [int(scene_max_chars) if scene_max_chars is not None else config.chunking.max_chars]
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
    prepared_segments: Mapping[str, PreparedSegment],
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
    if endpoint.supported_provider_options is not None:
        unsupported_options = set(segment.provider_options) - endpoint.supported_provider_options
        if unsupported_options:
            return UnsupportedModelFeatureError(
                f"{kind.value} requests do not support provider option(s): "
                f"{', '.join(sorted(unsupported_options))}",
                context={"mode": kind.value, "segment_id": segment.id},
            )
    prepared = prepared_segments.get(segment.id)
    if prepared is not None:
        missing_features = prepared.features_used - endpoint.features
        if missing_features:
            return UnsupportedModelFeatureError(
                f"{kind.value} requests cannot honor translated feature(s): "
                f"{', '.join(sorted(feature.value for feature in missing_features))}",
                context={"mode": kind.value, "segment_id": segment.id},
            )
    if _setting(segment, "seed", config.seed) is not None and not endpoint.supports(
        ProviderFeature.SEED
    ):
        return UnsupportedModelFeatureError(
            f"{kind.value} requests do not support a generation seed",
            context={"mode": kind.value, "segment_id": segment.id},
        )
    if _setting(
        segment, "text_normalization", config.text_normalization
    ) != "auto" and not endpoint.supports(ProviderFeature.TEXT_NORMALIZATION):
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
    prepared_segments: Mapping[str, PreparedSegment],
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
                prepared_segments=prepared_segments,
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

    # Auto streaming favors independently attributable speech chunks. Explicit
    # dialogue remains available and is normalized after request completion.
    multi_speaker = (
        not streaming and len(segments) > 1 and len({item.speaker for item in segments}) > 1
    )
    preference = (
        (RequestKind.DIALOGUE, RequestKind.SPEECH)
        if multi_speaker
        else (RequestKind.SPEECH, RequestKind.DIALOGUE)
    )
    errors: list[CapabilityError] = []
    for kind in preference:
        endpoint, error = candidate(kind)
        if endpoint is not None and error is None:
            return kind, endpoint
        if error is not None:
            errors.append(error)
    raise errors[0]


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
    prepared_segments: Mapping[str, PreparedSegment],
) -> tuple[_RequestDraft, ...]:
    limit = _request_limit(config, endpoint, segments[0])
    parts_by_segment = [
        _parts_for_segment(
            segment,
            request_limit=limit,
            prepared=prepared_segments.get(segment.id),
        )
        for segment in segments
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
                timestamps=bool(_setting(part.segment, "timestamps", config.timestamps)),
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
    prepared_segments: Mapping[str, PreparedSegment] | None = None,
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
    prepared = {} if prepared_segments is None else dict(prepared_segments)
    segment_ids = {segment.id for segment in compiled.segments}
    unknown_prepared_ids = set(prepared) - segment_ids
    if unknown_prepared_ids:
        raise CapabilityError(
            "Prepared provider text references unknown segment(s): "
            f"{', '.join(sorted(unknown_prepared_ids))}"
        )
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
            prepared_segments=prepared,
        )
        for draft in _request_drafts(
            pending,
            kind=kind,
            endpoint=endpoint,
            config=config,
            streaming=streaming,
            prepared_segments=prepared,
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
                elif pending:
                    previous_prepared = prepared.get(pending[-1].id)
                    current_prepared = prepared.get(event.id)
                    previous_version = (
                        previous_prepared.translation_version
                        if previous_prepared is not None
                        else None
                    )
                    current_version = (
                        current_prepared.translation_version
                        if current_prepared is not None
                        else None
                    )
                    if previous_version != current_version:
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
