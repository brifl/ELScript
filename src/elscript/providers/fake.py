"""Deterministic no-network provider for planner and integration tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from typing import Any

from .base import (
    EndpointCapabilities,
    GenerationChunk,
    GenerationResult,
    ProviderCapabilities,
    ProviderFeature,
    ProviderRequest,
)

_FAKE_FEATURES = frozenset(
    {
        ProviderFeature.STREAMING,
        ProviderFeature.TIMESTAMPS,
        ProviderFeature.SPEAKER_SEGMENTS,
        ProviderFeature.PRONUNCIATION_DICTIONARIES,
        ProviderFeature.NATIVE_IPA,
        ProviderFeature.REQUEST_STITCHING,
        ProviderFeature.SEED,
        ProviderFeature.TEXT_NORMALIZATION,
        ProviderFeature.LANGUAGE_NORMALIZATION,
        ProviderFeature.REQUEST_LOGGING_CONTROL,
        ProviderFeature.VOICE_SETTINGS,
        ProviderFeature.AUDIO_TAGS,
    }
)


def fake_capabilities(*, request_chars: int = 2_000) -> ProviderCapabilities:
    """Return permissive, bounded capabilities suitable for deterministic tests."""

    speech = EndpointCapabilities(
        features=_FAKE_FEATURES,
        recommended_request_chars=request_chars,
        hard_request_chars=request_chars,
        max_pronunciation_dictionaries=3,
    )
    return ProviderCapabilities(
        provider_id="fake",
        speech=speech,
        dialogue=EndpointCapabilities(
            features=_FAKE_FEATURES,
            recommended_request_chars=request_chars,
            hard_request_chars=request_chars,
            max_unique_voices=10,
            max_pronunciation_dictionaries=3,
        ),
        capability_version="fake-v1",
    )


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    return value


def _request_identity(request: ProviderRequest) -> bytes:
    payload = {
        "kind": request.kind.value,
        "model": request.model,
        "language": request.language,
        "output_format": request.output_format,
        "timestamps": request.timestamps,
        "streaming": request.streaming,
        "dictionaries": [
            {"id": locator.id, "version_id": locator.version_id}
            for locator in request.dictionary_locators
        ],
        "render_settings": _plain(request.render_settings),
        "provider_options": _plain(request.provider_options),
        "parts": [
            {
                "voice_id": part.segment.voice_id,
                "text": part.text,
                "cues": part.segment.cues,
                "tags": part.segment.tags,
                "performance": {
                    "emotion": part.segment.performance.emotion,
                    "intensity": part.segment.performance.intensity,
                    "energy": part.segment.performance.energy,
                    "pace": part.segment.performance.pace,
                    "volume": part.segment.performance.volume,
                    "delivery": part.segment.performance.delivery,
                    "accent": part.segment.performance.accent,
                },
            }
            for part in request.parts
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class FakeProvider:
    """Records calls and emits stable opaque bytes without external side effects."""

    provider_id = "fake"

    def __init__(self, capabilities: ProviderCapabilities | None = None) -> None:
        self._capabilities = capabilities or fake_capabilities()
        if self._capabilities.provider_id != self.provider_id:
            raise ValueError("fake capabilities must use provider_id='fake'")
        self._requests: list[ProviderRequest] = []

    @property
    def requests(self) -> tuple[ProviderRequest, ...]:
        return tuple(self._requests)

    def describe_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def generate(self, request: ProviderRequest) -> GenerationResult:
        self._requests.append(request)
        digest = hashlib.sha256(_request_identity(request)).hexdigest()
        return GenerationResult(
            audio=f"elscript-fake:{digest}".encode(),
            output_format=request.output_format,
            request_id=f"fake-{digest[:16]}",
            metadata={"deterministic": True},
        )

    def stream(self, request: ProviderRequest) -> Iterator[GenerationChunk]:
        result = self.generate(request)
        yield GenerationChunk(
            audio=result.audio,
            output_format=result.output_format,
            request_id=result.request_id,
            final=True,
            metadata=result.metadata,
        )
