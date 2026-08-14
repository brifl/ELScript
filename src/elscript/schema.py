"""Strict structural models for the ELScript 1.0 authoring language."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

NonEmptyString = Annotated[str, Field(min_length=1)]
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
ResetField = Literal["emotion", "intensity", "energy", "pace", "volume", "delivery", "accent"]
ResetValue = Literal["all"] | ResetField | Annotated[list[ResetField], Field(min_length=1)]
CueValue = NonEmptyString | Annotated[list[NonEmptyString], Field(min_length=1)]
ApiOptions = dict[str, Any]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, strict=True)


class PerformanceState(StrictModel):
    emotion: NonEmptyString | None = None
    intensity: UnitFloat | None = None
    energy: UnitFloat | None = None
    pace: NonEmptyString | None = None
    volume: NonEmptyString | None = None
    delivery: list[NonEmptyString] | None = None
    accent: NonEmptyString | None = None


class Preset(PerformanceState):
    api: ApiOptions = Field(default_factory=dict)


class Character(StrictModel):
    voice_id: NonEmptyString
    preset: NonEmptyString | None = None
    model: NonEmptyString | None = None
    language: NonEmptyString | None = None
    defaults: PerformanceState = Field(default_factory=PerformanceState)
    api: ApiOptions = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class Meta(StrictModel):
    id: NonEmptyString | None = None
    title: NonEmptyString | None = None
    description: str | None = None
    author: NonEmptyString | None = None
    language: NonEmptyString | None = None
    tags: list[NonEmptyString] = Field(default_factory=list)


class Chunking(StrictModel):
    max_chars: Annotated[int, Field(gt=0)] | None = None
    prefer_scene_boundaries: bool | None = None
    prefer_utterance_boundaries: bool | None = None
    preserve_continuity: bool | None = None


class RenderSettings(StrictModel):
    provider: NonEmptyString | None = None
    mode: Literal["auto", "speech", "dialogue"] | None = None
    model: NonEmptyString | None = None
    output_format: NonEmptyString | None = None
    timestamps: bool | None = None
    seed: int | None = None
    text_normalization: Literal["auto", "on", "off"] | None = None
    language_text_normalization: bool | None = None
    enable_logging: bool | None = None
    chunking: Chunking | None = None
    api: ApiOptions = Field(default_factory=dict)


class DictionaryReference(StrictModel):
    id: NonEmptyString
    version_id: NonEmptyString


class PronunciationTerm(StrictModel):
    ipa: NonEmptyString | None = None
    say_as: NonEmptyString | None = None

    @model_validator(mode="after")
    def require_pronunciation(self) -> PronunciationTerm:
        if self.ipa is None and self.say_as is None:
            raise ValueError("a pronunciation term requires ipa or say_as")
        return self


class Pronunciation(StrictModel):
    dictionaries: list[DictionaryReference] = Field(default_factory=list)
    terms: dict[NonEmptyString, PronunciationTerm] = Field(default_factory=dict)


class StructuredSayItem(StrictModel):
    text: NonEmptyString | None = None
    set_: PerformanceState | None = Field(default=None, alias="set")
    with_: PerformanceState | None = Field(default=None, alias="with")
    reset: ResetValue | None = None
    cue: CueValue | None = None
    tags: list[NonEmptyString] | None = None
    api: ApiOptions | None = None

    @model_validator(mode="after")
    def require_effect(self) -> StructuredSayItem:
        has_persistent_effect = self.set_ is not None or self.reset is not None
        has_vocal_effect = self.text is not None or self.cue is not None or bool(self.tags)
        if not has_persistent_effect and not has_vocal_effect:
            raise ValueError("a structured say item must contain at least one command")
        if self.with_ is not None and not has_vocal_effect:
            raise ValueError("with requires text, cue, or tags in the same structured item")
        return self


class SpeechPayload(StrictModel):
    id: NonEmptyString | None = None
    set_: PerformanceState | None = Field(default=None, alias="set")
    with_: PerformanceState | None = Field(default=None, alias="with")
    reset: ResetValue | None = None
    cue: CueValue | None = None
    tags: list[NonEmptyString] | None = None
    say: NonEmptyString | list[StructuredSayItem] | None = None
    api: ApiOptions = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_effect(self) -> SpeechPayload:
        has_persistent_effect = self.set_ is not None or self.reset is not None
        has_vocal_effect = self.cue is not None or bool(self.tags) or self.say is not None
        if not has_persistent_effect and not has_vocal_effect:
            raise ValueError("a speech entry must contain speech or a state command")
        if self.with_ is not None and not has_vocal_effect:
            raise ValueError("with requires say, cue, or tags in the same speech entry")
        return self


class ScriptEntry(RootModel[dict[str, Any]]):
    model_config = ConfigDict(frozen=True, strict=True)

    @model_validator(mode="after")
    def validate_entry(self) -> ScriptEntry:
        entry = self.root
        if len(entry) != 1:
            raise ValueError("a script entry must contain exactly one event or character")

        key, value = next(iter(entry.items()))
        if not isinstance(key, str) or not key:
            raise ValueError("a script entry key must be a non-empty string")
        if key == "pause":
            valid_pause = (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
                and value >= 0
            )
            if not valid_pause:
                raise ValueError("pause must be a non-negative number of seconds")
            return self
        if key in {"note", "marker"}:
            if not isinstance(value, str) or not value:
                raise ValueError(f"{key} must be a non-empty string")
            return self
        if isinstance(value, str):
            if not value:
                raise ValueError("speech text must not be empty")
            return self
        SpeechPayload.model_validate(value)
        return self


class Scene(StrictModel):
    id: NonEmptyString
    order: int | float | None = None
    title: NonEmptyString | None = None
    context: str | None = None
    inherit_character_state: bool = False
    render: RenderSettings | None = None
    api: ApiOptions = Field(default_factory=dict)
    script: list[ScriptEntry]

    @field_validator("order", mode="before")
    @classmethod
    def require_finite_numeric_order(cls, value: object) -> object:
        if isinstance(value, bool) or (
            isinstance(value, (int, float)) and not math.isfinite(value)
        ):
            raise ValueError("scene order must be numeric, not boolean")
        return value


class ManifestSettings(StrictModel):
    enabled: bool = True
    include_source_text: bool = True


class MetadataSettings(StrictModel):
    save_request_ids: bool = True
    save_voice_segments: bool = True
    save_character_timestamps: bool = True
    save_normalized_timestamps: bool = True


class ExportSettings(StrictModel):
    mode: Literal["single", "scene", "segment"] = "single"
    normalize_loudness: bool = False
    manifest: ManifestSettings = Field(default_factory=ManifestSettings)
    metadata: MetadataSettings = Field(default_factory=MetadataSettings)


class ELScriptDocument(StrictModel):
    elscript: Literal["1.0"]
    meta: Meta = Field(default_factory=Meta)
    render: RenderSettings = Field(default_factory=RenderSettings)
    pronunciation: Pronunciation = Field(default_factory=Pronunciation)
    presets: dict[NonEmptyString, Preset] = Field(default_factory=dict)
    characters: dict[NonEmptyString, Character]
    scenes: list[Scene]
    export: ExportSettings = Field(default_factory=ExportSettings)

    @model_validator(mode="after")
    def require_unique_scene_ids(self) -> ELScriptDocument:
        scene_ids = [scene.id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("scene ids must be unique")
        return self
