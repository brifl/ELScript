"""Provider contracts and built-in adapters."""

from .base import (
    CharacterAlignment,
    DictionaryLocator,
    EndpointCapabilities,
    GenerationChunk,
    GenerationResult,
    PlannedSegmentPart,
    Provider,
    ProviderCapabilities,
    ProviderFeature,
    ProviderRequest,
    RequestKind,
    VoiceSegmentMetadata,
)
from .fake import FakeProvider, fake_capabilities

__all__ = [
    "CharacterAlignment",
    "DictionaryLocator",
    "EndpointCapabilities",
    "FakeProvider",
    "GenerationChunk",
    "GenerationResult",
    "PlannedSegmentPart",
    "Provider",
    "ProviderCapabilities",
    "ProviderFeature",
    "ProviderRequest",
    "RequestKind",
    "VoiceSegmentMetadata",
    "fake_capabilities",
]
