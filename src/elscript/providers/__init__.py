"""Provider contracts and built-in adapters."""

from .base import (
    CharacterAlignment,
    DictionaryLocator,
    EndpointCapabilities,
    GenerationChunk,
    GenerationResult,
    PlannedSegmentPart,
    PreparedSegment,
    Provider,
    ProviderCapabilities,
    ProviderFeature,
    ProviderRequest,
    RequestKind,
    VoiceSegmentMetadata,
)
from .elevenlabs import (
    ElevenLabsProvider,
    ElevenLabsTransport,
    TransportRequest,
    TransportResponse,
    UrllibElevenLabsTransport,
)
from .fake import FakeProvider, fake_capabilities

__all__ = [
    "CharacterAlignment",
    "DictionaryLocator",
    "EndpointCapabilities",
    "ElevenLabsProvider",
    "ElevenLabsTransport",
    "FakeProvider",
    "GenerationChunk",
    "GenerationResult",
    "PlannedSegmentPart",
    "PreparedSegment",
    "Provider",
    "ProviderCapabilities",
    "ProviderFeature",
    "ProviderRequest",
    "RequestKind",
    "TransportRequest",
    "TransportResponse",
    "UrllibElevenLabsTransport",
    "VoiceSegmentMetadata",
    "fake_capabilities",
]
