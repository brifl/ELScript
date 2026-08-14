"""Compile validated ELScript scenes into a provider-neutral timeline."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .config import EffectiveConfig
from .domain import (
    CompiledScene,
    CompiledScript,
    MarkerEvent,
    NoteEvent,
    PauseEvent,
    ResolvedPerformance,
    SpeechSegment,
    TimelineItem,
)
from .errors import InvalidStateError
from .schema import ELScriptDocument, PerformanceState, SpeechPayload

_LIBRARY_PERFORMANCE_DEFAULTS: dict[str, Any] = {
    "emotion": "neutral",
    "intensity": 0.0,
    "energy": 0.0,
    "pace": "normal",
    "volume": "normal",
    "delivery": (),
    "accent": None,
}
_PERFORMANCE_FIELDS = frozenset(_LIBRARY_PERFORMANCE_DEFAULTS)
_EVENT_KEYS = frozenset({"pause", "note", "marker"})


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if isinstance(item, Mapping):
            return MappingProxyType({str(key): freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    frozen = freeze(value)
    if not isinstance(frozen, Mapping):
        raise TypeError("mapping freeze invariant was violated")
    return frozen


def _overlay(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for key, value in incoming.items():
        if value is None:
            continue
        if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
            nested = dict(target[key])
            _overlay(nested, value)
            target[key] = nested
        else:
            target[key] = deepcopy(value)


def _state_values(state: PerformanceState | None) -> dict[str, Any]:
    if state is None:
        return {}
    values = {
        key: value
        for key, value in state.model_dump(exclude_none=True, by_alias=True).items()
        if key in _PERFORMANCE_FIELDS
    }
    if "delivery" in values:
        values["delivery"] = tuple(values["delivery"])
    return values


def _resolved(values: Mapping[str, Any]) -> ResolvedPerformance:
    return ResolvedPerformance(
        emotion=values["emotion"],
        intensity=values["intensity"],
        energy=values["energy"],
        pace=values["pace"],
        volume=values["volume"],
        delivery=tuple(values["delivery"]),
        accent=values["accent"],
    )


def _baseline_states(document: ELScriptDocument) -> dict[str, dict[str, Any]]:
    baselines: dict[str, dict[str, Any]] = {}
    for character_id, character in document.characters.items():
        state = deepcopy(_LIBRARY_PERFORMANCE_DEFAULTS)
        if character.preset is not None:
            _overlay(state, _state_values(document.presets[character.preset]))
        _overlay(state, _state_values(character.defaults))
        baselines[character_id] = state
    return baselines


def _reset_state(
    current: dict[str, Any],
    baseline: Mapping[str, Any],
    reset: str | Sequence[str] | None,
) -> None:
    if reset is None:
        return
    if reset == "all":
        current.clear()
        current.update(deepcopy(dict(baseline)))
        return
    reset_fields = [reset] if isinstance(reset, str) else list(reset)
    for field_name in reset_fields:
        current[field_name] = deepcopy(baseline[field_name])


def _cue_values(value: str | list[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _speaker_slug(speaker: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", speaker.casefold()).strip("-")
    return slug or "speaker"


@dataclass(slots=True)
class _SegmentDraft:
    text: str | None
    performance: ResolvedPerformance
    provider_options: Mapping[str, Any]
    cues: tuple[str, ...]
    tags: tuple[str, ...]


def _provider_options(
    config: EffectiveConfig,
    *,
    preset_api: Mapping[str, Any],
    character_api: Mapping[str, Any],
    scene_render_api: Mapping[str, Any],
    scene_api: Mapping[str, Any],
    utterance_api: Mapping[str, Any],
    segment_api: Mapping[str, Any],
) -> Mapping[str, Any]:
    values = dict(config.api)
    for layer in (
        preset_api,
        character_api,
        scene_render_api,
        scene_api,
        utterance_api,
        segment_api,
    ):
        _overlay(values, layer)
    return _freeze_mapping(values)


def _render_settings(
    config: EffectiveConfig,
    scene_render: Mapping[str, Any],
    *,
    model: str,
    language: str | None,
) -> Mapping[str, Any]:
    values: dict[str, Any] = {
        "provider": config.provider,
        "render_mode": config.render_mode,
        "model": model,
        "language": language,
        "output_format": config.output_format,
        "timestamps": config.timestamps,
        "seed": config.seed,
        "text_normalization": config.text_normalization,
        "language_text_normalization": config.language_text_normalization,
        "enable_logging": config.enable_logging,
    }
    overrides = {key: value for key, value in scene_render.items() if key != "api"}
    if "mode" in overrides:
        overrides["render_mode"] = overrides.pop("mode")
    _overlay(values, overrides)
    values["model"] = overrides.get("model", model)
    return _freeze_mapping(values)


def _compile_payload(
    payload: SpeechPayload,
    *,
    current: dict[str, Any],
    baseline: Mapping[str, Any],
    provider_base: tuple[
        EffectiveConfig,
        Mapping[str, Any],
        Mapping[str, Any],
        Mapping[str, Any],
        Mapping[str, Any],
    ],
) -> list[_SegmentDraft]:
    config, preset_api, character_api, scene_render_api, scene_api = provider_base
    _reset_state(current, baseline, payload.reset)
    _overlay(current, _state_values(payload.set_))
    parent_state = deepcopy(current)
    _overlay(parent_state, _state_values(payload.with_))
    parent_cues = _cue_values(payload.cue)
    parent_tags = tuple(payload.tags or ())
    utterance_api = payload.api

    if isinstance(payload.say, str):
        return [
            _SegmentDraft(
                text=payload.say,
                performance=_resolved(parent_state),
                provider_options=_provider_options(
                    config,
                    preset_api=preset_api,
                    character_api=character_api,
                    scene_render_api=scene_render_api,
                    scene_api=scene_api,
                    utterance_api=utterance_api,
                    segment_api={},
                ),
                cues=parent_cues,
                tags=parent_tags,
            )
        ]

    if payload.say is None:
        if not parent_cues and not parent_tags:
            return []
        return [
            _SegmentDraft(
                text=None,
                performance=_resolved(parent_state),
                provider_options=_provider_options(
                    config,
                    preset_api=preset_api,
                    character_api=character_api,
                    scene_render_api=scene_render_api,
                    scene_api=scene_api,
                    utterance_api=utterance_api,
                    segment_api={},
                ),
                cues=parent_cues,
                tags=parent_tags,
            )
        ]

    drafts: list[_SegmentDraft] = []
    parent_directions_pending = bool(parent_cues or parent_tags)
    for item in payload.say:
        _reset_state(current, baseline, item.reset)
        _overlay(current, _state_values(item.set_))
        item_cues = _cue_values(item.cue)
        item_tags = tuple(item.tags or ())
        is_vocal = item.text is not None or bool(item_cues) or bool(item_tags)
        if not is_vocal:
            continue

        effective_state = deepcopy(current)
        _overlay(effective_state, _state_values(payload.with_))
        _overlay(effective_state, _state_values(item.with_))
        cues = item_cues
        tags = item_tags
        if parent_directions_pending:
            cues = parent_cues + cues
            tags = parent_tags + tags
            parent_directions_pending = False
        drafts.append(
            _SegmentDraft(
                text=item.text,
                performance=_resolved(effective_state),
                provider_options=_provider_options(
                    config,
                    preset_api=preset_api,
                    character_api=character_api,
                    scene_render_api=scene_render_api,
                    scene_api=scene_api,
                    utterance_api=utterance_api,
                    segment_api=item.api or {},
                ),
                cues=cues,
                tags=tags,
            )
        )
    if parent_directions_pending:
        drafts.insert(
            0,
            _SegmentDraft(
                text=None,
                performance=_resolved(parent_state),
                provider_options=_provider_options(
                    config,
                    preset_api=preset_api,
                    character_api=character_api,
                    scene_render_api=scene_render_api,
                    scene_api=scene_api,
                    utterance_api=utterance_api,
                    segment_api={},
                ),
                cues=parent_cues,
                tags=parent_tags,
            ),
        )
    return drafts


def _entry_segment_ids(
    *,
    explicit_id: str | None,
    scene_id: str,
    speaker: str,
    entry_index: int,
    count: int,
) -> tuple[str, ...]:
    base = explicit_id or f"{scene_id}.{_speaker_slug(speaker)}.{entry_index + 1:04d}"
    if count == 1:
        return (base,)
    if explicit_id is not None:
        return (base, *(f"{base}.{part + 1:02d}" for part in range(1, count)))
    return tuple(f"{base}.{part + 1:02d}" for part in range(count))


def _state_snapshot(states: Mapping[str, Mapping[str, Any]]) -> Mapping[str, ResolvedPerformance]:
    return MappingProxyType({key: _resolved(value) for key, value in states.items()})


def compile_document(document: ELScriptDocument, config: EffectiveConfig) -> CompiledScript:
    """Resolve sticky character state and ordered events without provider generation."""

    baselines = _baseline_states(document)
    current_states = deepcopy(baselines)
    timeline: list[TimelineItem] = []
    segments: list[SpeechSegment] = []
    compiled_scenes: list[CompiledScene] = []
    used_segment_ids: set[str] = set()
    ordinal = 0

    for scene in document.scenes:
        if not scene.inherit_character_state:
            current_states = deepcopy(baselines)
        initial_states = _state_snapshot(current_states)
        scene_events: list[TimelineItem] = []
        scene_render = (
            scene.render.model_dump(exclude_none=True, exclude_unset=True, by_alias=True)
            if scene.render
            else {}
        )
        scene_render_api = scene_render.get("api", {})

        for entry_index, script_entry in enumerate(scene.script):
            key, raw_payload = next(iter(script_entry.root.items()))
            if key == "pause":
                pause_event = PauseEvent(scene.id, float(raw_payload), ordinal)
                scene_events.append(pause_event)
                timeline.append(pause_event)
                continue
            if key == "marker":
                marker_event = MarkerEvent(scene.id, str(raw_payload), ordinal)
                scene_events.append(marker_event)
                timeline.append(marker_event)
                continue
            if key == "note":
                note_event = NoteEvent(scene.id, str(raw_payload), ordinal)
                scene_events.append(note_event)
                timeline.append(note_event)
                continue
            if key in _EVENT_KEYS:
                raise InvalidStateError(f"Unsupported timeline event {key!r}")

            character = document.characters[key]
            payload = (
                SpeechPayload(say=raw_payload)
                if isinstance(raw_payload, str)
                else SpeechPayload.model_validate(raw_payload)
            )
            preset_api = (
                document.presets[character.preset].api if character.preset is not None else {}
            )
            drafts = _compile_payload(
                payload,
                current=current_states[key],
                baseline=baselines[key],
                provider_base=(
                    config,
                    preset_api,
                    character.api,
                    scene_render_api,
                    scene.api,
                ),
            )
            ids = _entry_segment_ids(
                explicit_id=payload.id,
                scene_id=scene.id,
                speaker=key,
                entry_index=entry_index,
                count=len(drafts),
            )
            model = character.model or config.model
            if "model" in scene_render:
                model = scene_render["model"]
            language = character.language or config.language
            render_settings = _render_settings(
                config,
                scene_render,
                model=model,
                language=language,
            )

            for segment_id, draft in zip(ids, drafts, strict=True):
                if segment_id in used_segment_ids:
                    raise InvalidStateError(
                        f"Compiled speech segment id is not unique: {segment_id}"
                    )
                used_segment_ids.add(segment_id)
                ordinal += 1
                segment = SpeechSegment(
                    id=segment_id,
                    entry_id=payload.id,
                    scene_id=scene.id,
                    ordinal=ordinal,
                    speaker=key,
                    voice_id=character.voice_id,
                    model=model,
                    language=language,
                    text=draft.text,
                    performance=draft.performance,
                    provider_options=draft.provider_options,
                    render_settings=render_settings,
                    cues=draft.cues,
                    tags=draft.tags,
                )
                segments.append(segment)
                scene_events.append(segment)
                timeline.append(segment)

        compiled_scenes.append(
            CompiledScene(
                id=scene.id,
                title=scene.title,
                context=scene.context,
                events=tuple(scene_events),
                initial_character_states=initial_states,
                final_character_states=_state_snapshot(current_states),
            )
        )

    script_id = document.meta.id or (
        _speaker_slug(document.meta.title) if document.meta.title else "output"
    )
    return CompiledScript(
        script_id=script_id,
        scenes=tuple(compiled_scenes),
        timeline=tuple(timeline),
        segments=tuple(segments),
        final_character_states=_state_snapshot(current_states),
    )
