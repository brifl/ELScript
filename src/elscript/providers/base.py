"""Provider-neutral capability, request, generation, and streaming contracts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from ..domain import SpeechSegment


class RequestKind(StrEnum):
    """Provider operation selected for one render request."""

    SPEECH = "speech"
    DIALOGUE = "dialogue"


class ProviderFeature(StrEnum):
    """Endpoint behavior that must be checked before generation."""

    STREAMING = "streaming"
    TIMESTAMPS = "timestamps"
    SPEAKER_SEGMENTS = "speaker_segments"
    PRONUNCIATION_DICTIONARIES = "pronunciation_dictionaries"
    NATIVE_IPA = "native_ipa"
    REQUEST_STITCHING = "request_stitching"
    SEED = "seed"
    TEXT_NORMALIZATION = "text_normalization"
    LANGUAGE_NORMALIZATION = "language_normalization"
    REQUEST_LOGGING_CONTROL = "request_logging_control"
    VOICE_SETTINGS = "voice_settings"
    AUDIO_TAGS = "audio_tags"


@dataclass(frozen=True, slots=True)
class EndpointCapabilities:
    """Known static and discovered constraints for one provider operation."""

    features: frozenset[ProviderFeature] = frozenset()
    supported_models: frozenset[str] | None = None
    supported_output_formats: frozenset[str] | None = None
    recommended_request_chars: int | None = None
    hard_request_chars: int | None = None
    max_unique_voices: int = 1
    max_pronunciation_dictionaries: int = 0
    supported_provider_options: frozenset[str] | None = None

    def __post_init__(self) -> None:
        for name in ("recommended_request_chars", "hard_request_chars"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be positive when supplied")
        if self.max_unique_voices < 1:
            raise ValueError("max_unique_voices must be positive")
        if self.max_pronunciation_dictionaries < 0:
            raise ValueError("max_pronunciation_dictionaries must not be negative")

    def supports(self, feature: ProviderFeature) -> bool:
        return feature in self.features


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Endpoint-specific provider capabilities used by the pure planner."""

    provider_id: str
    speech: EndpointCapabilities | None
    dialogue: EndpointCapabilities | None = None
    capability_version: str = "1"

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id must not be empty")
        if self.speech is None and self.dialogue is None:
            raise ValueError("a provider must expose at least one generation endpoint")

    def for_kind(self, kind: RequestKind) -> EndpointCapabilities | None:
        return self.speech if kind is RequestKind.SPEECH else self.dialogue


@dataclass(frozen=True, slots=True)
class DictionaryLocator:
    id: str
    version_id: str

    def __post_init__(self) -> None:
        if not self.id or not self.version_id:
            raise ValueError("dictionary id and version_id must not be empty")


@dataclass(frozen=True, slots=True)
class PlannedSegmentPart:
    """An ordered provider-sized part retaining its authored segment identity."""

    segment: SpeechSegment
    text: str | None
    part_index: int = 1
    part_count: int = 1
    translation_version: str | None = None
    features_used: frozenset[ProviderFeature] = frozenset()

    def __post_init__(self) -> None:
        if self.part_count < 1 or not 1 <= self.part_index <= self.part_count:
            raise ValueError("part_index must identify a valid one-based part")

    @property
    def logical_id(self) -> str:
        return self.segment.id


@dataclass(frozen=True, slots=True)
class PreparedSegment:
    """Provider-ready text produced before character-aware request splitting."""

    text: str | None
    translation_version: str
    prefix: str = ""
    features_used: frozenset[ProviderFeature] = frozenset()
    atomic_tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.translation_version or (not self.prefix and not self.text):
            raise ValueError("prepared content and translation_version must not be empty")
        if any(not token for token in self.atomic_tokens):
            raise ValueError("atomic provider-text tokens must not be empty")

    @property
    def provider_text(self) -> str:
        return " ".join(value for value in (self.prefix, self.text) if value)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """One chargeable provider request selected by render planning."""

    id: str
    kind: RequestKind
    scene_id: str
    parts: tuple[PlannedSegmentPart, ...]
    model: str
    language: str | None
    output_format: str
    timestamps: bool
    streaming: bool
    character_count: int
    dictionary_locators: tuple[DictionaryLocator, ...] = ()
    render_settings: Mapping[str, Any] = field(default_factory=dict)
    provider_options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.parts:
            raise ValueError("a provider request requires an id and at least one part")
        if self.character_count < 0:
            raise ValueError("character_count must not be negative")
        if any(part.segment.scene_id != self.scene_id for part in self.parts):
            raise ValueError("provider requests must not cross scene boundaries")


@dataclass(frozen=True, slots=True)
class CharacterAlignment:
    characters: tuple[str, ...]
    start_seconds: tuple[float, ...]
    end_seconds: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class VoiceSegmentMetadata:
    voice_id: str
    start_seconds: float
    end_seconds: float
    part_index: int | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Normalized output from one non-streaming provider request."""

    audio: bytes
    output_format: str
    request_id: str | None = None
    duration_seconds: float | None = None
    alignment: CharacterAlignment | None = None
    normalized_alignment: CharacterAlignment | None = None
    voice_segments: tuple[VoiceSegmentMetadata, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GenerationChunk:
    """One provider stream chunk before ELScript timeline attribution."""

    audio: bytes
    output_format: str
    request_id: str | None = None
    final: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Provider(Protocol):
    """Adapter boundary; implementations own transport and provider translation."""

    @property
    def provider_id(self) -> str: ...

    def describe_capabilities(self) -> ProviderCapabilities: ...

    def generate(self, request: ProviderRequest) -> GenerationResult: ...

    def stream(self, request: ProviderRequest) -> Iterator[GenerationChunk]: ...
