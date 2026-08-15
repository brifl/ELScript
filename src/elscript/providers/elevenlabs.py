"""ElevenLabs HTTP execution and provider-neutral response translation."""

from __future__ import annotations

import base64
import binascii
import codecs
import json
import math
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ..errors import (
    AuthenticationError,
    CapabilityError,
    GenerationError,
    ProviderAccountError,
    ProviderLimitError,
    RateLimitError,
)
from ..redaction import REDACTED, SecretValue
from .base import (
    CharacterAlignment,
    GenerationChunk,
    GenerationResult,
    ProviderCapabilities,
    ProviderRequest,
    VoiceSegmentMetadata,
)
from .elevenlabs_prompt import (
    ElevenLabsOperation,
    ElevenLabsRequest,
    build_elevenlabs_request,
    elevenlabs_capabilities,
)

_API_BASE_URL = "https://api.elevenlabs.io"
_REQUEST_ID_HEADERS = ("request-id", "x-request-id")
_TIMESTAMP_OPERATIONS = frozenset(
    {
        ElevenLabsOperation.CREATE_SPEECH_WITH_TIMESTAMPS,
        ElevenLabsOperation.STREAM_SPEECH_WITH_TIMESTAMPS,
        ElevenLabsOperation.CREATE_DIALOGUE_WITH_TIMESTAMPS,
        ElevenLabsOperation.STREAM_DIALOGUE_WITH_TIMESTAMPS,
    }
)
_STREAM_OPERATIONS = frozenset(
    {
        ElevenLabsOperation.STREAM_SPEECH,
        ElevenLabsOperation.STREAM_SPEECH_WITH_TIMESTAMPS,
        ElevenLabsOperation.STREAM_DIALOGUE,
        ElevenLabsOperation.STREAM_DIALOGUE_WITH_TIMESTAMPS,
    }
)
_ACCOUNT_ERROR_TERMS = (
    "account",
    "billing",
    "payment",
    "plan",
    "quota",
    "subscription",
)
_CAPABILITY_ERROR_TERMS = (
    "capability",
    "format",
    "model",
    "not_found",
    "unsupported",
    "voice",
)
_LIMIT_ERROR_TERMS = ("character_limit", "limit_exceeded", "too_many")
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class TransportRequest:
    """Material HTTP request; credentials are excluded from ordinary representations."""

    method: str
    url: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


@dataclass(slots=True)
class TransportStreamResponse:
    """Incremental HTTP response with explicit resource ownership."""

    status: int
    headers: Mapping[str, str]
    chunks: Iterator[bytes] = field(repr=False)
    close_callback: Callable[[], None] | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close_chunks = getattr(self.chunks, "close", None)
        try:
            if callable(close_chunks):
                close_chunks()
        finally:
            if self.close_callback is not None:
                self.close_callback()


class ElevenLabsTransport(Protocol):
    """Injectable boundary used to guarantee charge-free adapter tests."""

    def send(self, request: TransportRequest) -> TransportResponse: ...

    def stream(self, request: TransportRequest) -> TransportStreamResponse: ...


class UrllibElevenLabsTransport:
    """Small production HTTP transport with no third-party runtime dependency."""

    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds

    def send(self, request: TransportRequest) -> TransportResponse:
        outgoing = self._outgoing(request)
        try:
            with urlopen(outgoing, timeout=self._timeout_seconds) as response:  # noqa: S310
                return TransportResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as error:
            return TransportResponse(
                status=error.code,
                headers=dict(error.headers.items()) if error.headers is not None else {},
                body=error.read(),
            )
        except URLError as error:
            raise OSError("ElevenLabs transport failed") from error

    def stream(self, request: TransportRequest) -> TransportStreamResponse:
        outgoing = self._outgoing(request)
        try:
            response = urlopen(outgoing, timeout=self._timeout_seconds)  # noqa: S310
        except HTTPError as error:
            status = error.code
            headers = dict(error.headers.items()) if error.headers is not None else {}
            try:
                body = error.read()
            finally:
                error.close()
            return TransportStreamResponse(
                status=status,
                headers=headers,
                chunks=iter((body,)),
            )
        except URLError as error:
            raise OSError("ElevenLabs transport failed") from error

        def chunks() -> Iterator[bytes]:
            read_available = getattr(response, "read1", response.read)
            while chunk := read_available(64 * 1024):
                yield chunk

        return TransportStreamResponse(
            status=response.status,
            headers=dict(response.headers.items()),
            chunks=chunks(),
            close_callback=response.close,
        )

    @staticmethod
    def _outgoing(request: TransportRequest) -> Request:
        outgoing = Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        return outgoing


def _operation_path(request: ElevenLabsRequest) -> str:
    operation = request.operation
    if request.voice_id is not None:
        voice = quote(request.voice_id, safe="")
        suffix = {
            ElevenLabsOperation.CREATE_SPEECH: "",
            ElevenLabsOperation.CREATE_SPEECH_WITH_TIMESTAMPS: "/with-timestamps",
            ElevenLabsOperation.STREAM_SPEECH: "/stream",
            ElevenLabsOperation.STREAM_SPEECH_WITH_TIMESTAMPS: "/stream/with-timestamps",
        }.get(operation)
        if suffix is None:
            raise CapabilityError("ElevenLabs speech request selected a dialogue operation")
        return f"/v1/text-to-speech/{voice}{suffix}"
    suffix = {
        ElevenLabsOperation.CREATE_DIALOGUE: "",
        ElevenLabsOperation.CREATE_DIALOGUE_WITH_TIMESTAMPS: "/with-timestamps",
        ElevenLabsOperation.STREAM_DIALOGUE: "/stream",
        ElevenLabsOperation.STREAM_DIALOGUE_WITH_TIMESTAMPS: "/stream/with-timestamps",
    }.get(operation)
    if suffix is None:
        raise CapabilityError("ElevenLabs dialogue request selected a speech operation")
    return f"/v1/text-to-dialogue{suffix}"


def _query_string(query: Mapping[str, Any]) -> str:
    values = {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in query.items()
    }
    return urlencode(values)


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_compatible(item) for item in value]
    return value


def _header(headers: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    lowered = {key.casefold(): value for key, value in headers.items()}
    return next((lowered[name] for name in names if name in lowered), None)


def _json_object(body: bytes, *, response_name: str) -> Mapping[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GenerationError(f"ElevenLabs returned invalid {response_name} JSON") from error
    if not isinstance(value, Mapping):
        raise GenerationError(f"ElevenLabs returned a non-object {response_name}")
    return value


def _stream_json_objects(chunks: Iterator[bytes]) -> Iterator[Mapping[str, Any]]:
    """Decode adjacent or whitespace-delimited JSON objects across transport chunks."""

    text_decoder = codecs.getincrementaldecoder("utf-8")()
    json_decoder = json.JSONDecoder()
    buffered = ""

    def decoded() -> Iterator[Mapping[str, Any]]:
        nonlocal buffered
        while True:
            buffered = buffered.lstrip()
            if not buffered:
                return
            try:
                value, end = json_decoder.raw_decode(buffered)
            except json.JSONDecodeError:
                return
            if not isinstance(value, Mapping):
                raise GenerationError("ElevenLabs returned a non-object timestamp stream chunk")
            buffered = buffered[end:]
            yield value

    try:
        for chunk in chunks:
            buffered += text_decoder.decode(chunk)
            yield from decoded()
        buffered += text_decoder.decode(b"", final=True)
    except UnicodeDecodeError as error:
        raise GenerationError("ElevenLabs returned invalid timestamp stream JSON") from error
    yield from decoded()
    if buffered.strip():
        raise GenerationError("ElevenLabs returned invalid timestamp stream JSON")


def _mark_last(items: Iterator[_T]) -> Iterator[tuple[_T, bool]]:
    """Attach an EOF-derived final flag with at most one item of read-ahead."""

    try:
        current = next(items)
    except StopIteration:
        return
    for following in items:
        yield current, False
        current = following
    yield current, True


def _audio(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise GenerationError("ElevenLabs timestamp response omitted audio_base64")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise GenerationError(
            "ElevenLabs timestamp response contained invalid audio_base64"
        ) from error


def _number_sequence(value: Any, *, name: str) -> tuple[float, ...]:
    if not isinstance(value, list) or any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        for item in value
    ):
        raise GenerationError(f"ElevenLabs alignment field {name} must be numeric")
    return tuple(float(item) for item in value)


def _alignment(value: Any, *, name: str) -> CharacterAlignment | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise GenerationError(f"ElevenLabs {name} must be an object or null")
    characters = value.get("characters")
    if not isinstance(characters, list) or any(not isinstance(item, str) for item in characters):
        raise GenerationError(f"ElevenLabs {name}.characters must contain strings")
    starts = _number_sequence(
        value.get("character_start_times_seconds"),
        name=f"{name}.character_start_times_seconds",
    )
    ends = _number_sequence(
        value.get("character_end_times_seconds"),
        name=f"{name}.character_end_times_seconds",
    )
    if len(characters) != len(starts) or len(characters) != len(ends):
        raise GenerationError(f"ElevenLabs {name} fields have inconsistent lengths")
    if any(start < 0 or end < start for start, end in zip(starts, ends, strict=True)):
        raise GenerationError(f"ElevenLabs {name} contains invalid time bounds")
    return CharacterAlignment(tuple(characters), starts, ends)


def _required_number(value: Any, *, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise GenerationError(f"ElevenLabs voice segment field {name} must be numeric")
    return float(value)


def _optional_index(value: Any, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GenerationError(f"ElevenLabs voice segment field {name} must be non-negative")
    return value


def _voice_segments(value: Any) -> tuple[VoiceSegmentMetadata, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise GenerationError("ElevenLabs voice_segments must be a list")
    segments: list[VoiceSegmentMetadata] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise GenerationError("ElevenLabs voice_segments entries must be objects")
        voice_id = item.get("voice_id")
        part_index = item.get("dialogue_input_index")
        if not isinstance(voice_id, str) or not voice_id:
            raise GenerationError("ElevenLabs voice segment omitted voice_id")
        dialogue_input_index = _optional_index(part_index, name="dialogue_input_index")
        character_start_index = _optional_index(
            item.get("character_start_index"), name="character_start_index"
        )
        character_end_index = _optional_index(
            item.get("character_end_index"), name="character_end_index"
        )
        if (
            character_start_index is not None
            and character_end_index is not None
            and character_end_index < character_start_index
        ):
            raise GenerationError("ElevenLabs voice segment contains invalid character bounds")
        start = _required_number(item.get("start_time_seconds"), name="start_time_seconds")
        end = _required_number(item.get("end_time_seconds"), name="end_time_seconds")
        if start < 0 or end < start:
            raise GenerationError("ElevenLabs voice segment contains invalid time bounds")
        segments.append(
            VoiceSegmentMetadata(
                voice_id=voice_id,
                start_seconds=start,
                end_seconds=end,
                part_index=dialogue_input_index,
                character_start_index=character_start_index,
                character_end_index=character_end_index,
            )
        )
    return tuple(segments)


def _duration(
    alignment: CharacterAlignment | None,
    normalized_alignment: CharacterAlignment | None,
    voice_segments: tuple[VoiceSegmentMetadata, ...],
) -> float | None:
    candidates = [
        *(alignment.end_seconds if alignment is not None else ()),
        *(normalized_alignment.end_seconds if normalized_alignment is not None else ()),
        *(segment.end_seconds for segment in voice_segments),
    ]
    return max(candidates, default=None)


def _timestamp_fields(
    payload: Mapping[str, Any],
) -> tuple[
    bytes,
    CharacterAlignment | None,
    CharacterAlignment | None,
    tuple[VoiceSegmentMetadata, ...],
]:
    return (
        _audio(payload.get("audio_base64")),
        _alignment(payload.get("alignment"), name="alignment"),
        _alignment(payload.get("normalized_alignment"), name="normalized_alignment"),
        _voice_segments(payload.get("voice_segments")),
    )


def _provider_error_details(body: bytes, credential: SecretValue | None) -> tuple[str, str]:
    code = "unknown"
    message = ""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    detail = payload.get("detail") if isinstance(payload, Mapping) else None
    if isinstance(detail, Mapping):
        raw_code = detail.get("status", detail.get("code"))
        raw_message = detail.get("message")
    else:
        raw_code = payload.get("code") if isinstance(payload, Mapping) else None
        raw_message = payload.get("message") if isinstance(payload, Mapping) else None
    if isinstance(raw_code, str) and raw_code:
        code = raw_code[:100]
    if isinstance(raw_message, str):
        message = raw_message[:500]
    if credential is not None and credential.reveal():
        secret = credential.reveal()
        code = code.replace(secret, REDACTED)
        message = message.replace(secret, REDACTED)
    return code, message


def _raise_for_status(
    response: TransportResponse,
    *,
    request_id: str,
    credential: SecretValue | None,
) -> None:
    if 200 <= response.status < 300:
        return
    provider_code, provider_message = _provider_error_details(response.body, credential)
    context = {
        "provider": "elevenlabs",
        "request_id": request_id,
        "http_status": response.status,
        "provider_code": provider_code,
    }
    if provider_message:
        context["provider_message"] = provider_message
    normalized = f"{provider_code} {provider_message}".casefold()
    message = f"ElevenLabs request failed with HTTP {response.status} ({provider_code})"
    if response.status in {401, 403}:
        raise AuthenticationError(message, context=context)
    if response.status == 429:
        raise RateLimitError(message, context=context)
    if response.status == 402 or any(term in normalized for term in _ACCOUNT_ERROR_TERMS):
        raise ProviderAccountError(message, context=context)
    if any(term in normalized for term in _LIMIT_ERROR_TERMS):
        raise ProviderLimitError(message, context=context)
    if response.status in {400, 404, 409, 422} or any(
        term in normalized for term in _CAPABILITY_ERROR_TERMS
    ):
        raise CapabilityError(message, context=context)
    raise GenerationError(message, context=context)


class ElevenLabsProvider:
    """Execute validated plans against ElevenLabs through an injectable transport."""

    provider_id = "elevenlabs"

    def __init__(
        self,
        credential: SecretValue | str | None,
        *,
        transport: ElevenLabsTransport | None = None,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._credential = (
            credential
            if isinstance(credential, SecretValue)
            else SecretValue(credential)
            if credential is not None
            else None
        )
        self._transport = transport or UrllibElevenLabsTransport()
        self._capabilities = capabilities or elevenlabs_capabilities()
        if self._capabilities.provider_id != self.provider_id:
            raise ValueError("ElevenLabs capabilities must use provider_id='elevenlabs'")

    def describe_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def _transport_request(
        self, planned: ProviderRequest
    ) -> tuple[ElevenLabsRequest, TransportRequest]:
        if self._credential is None or not self._credential.reveal():
            raise AuthenticationError("An ElevenLabs API key is required")
        materialized = build_elevenlabs_request(planned, self._capabilities)
        query = _query_string(materialized.query)
        url = f"{_API_BASE_URL}{_operation_path(materialized)}"
        if query:
            url = f"{url}?{query}"
        return materialized, TransportRequest(
            method="POST",
            url=url,
            headers={
                "Content-Type": "application/json",
                "xi-api-key": self._credential.reveal(),
            },
            body=json.dumps(_json_compatible(materialized.body), separators=(",", ":")).encode(),
        )

    def _send(self, planned: ProviderRequest) -> tuple[ElevenLabsRequest, TransportResponse]:
        materialized, outgoing = self._transport_request(planned)
        try:
            response = self._transport.send(outgoing)
        except OSError as error:
            raise GenerationError(
                "ElevenLabs transport failed",
                context={"provider": self.provider_id, "request_id": planned.id},
            ) from error
        _raise_for_status(
            response,
            request_id=planned.id,
            credential=self._credential,
        )
        return materialized, response

    def _open_stream(
        self, planned: ProviderRequest
    ) -> tuple[ElevenLabsRequest, TransportStreamResponse]:
        materialized, outgoing = self._transport_request(planned)
        try:
            response = self._transport.stream(outgoing)
        except OSError as error:
            raise GenerationError(
                "ElevenLabs transport failed",
                context={"provider": self.provider_id, "request_id": planned.id},
            ) from error
        if not 200 <= response.status < 300:
            try:
                body = b"".join(response.chunks)
            finally:
                response.close()
            _raise_for_status(
                TransportResponse(response.status, response.headers, body),
                request_id=planned.id,
                credential=self._credential,
            )
        return materialized, response

    def generate(self, request: ProviderRequest) -> GenerationResult:
        if request.streaming:
            raise CapabilityError("Use ElevenLabsProvider.stream() for a streaming request")
        materialized, response = self._send(request)
        request_id = _header(response.headers, _REQUEST_ID_HEADERS)
        alignment = None
        normalized_alignment = None
        voice_segments: tuple[VoiceSegmentMetadata, ...] = ()
        if materialized.operation in _TIMESTAMP_OPERATIONS:
            payload = _json_object(response.body, response_name="timestamp response")
            audio, alignment, normalized_alignment, voice_segments = _timestamp_fields(payload)
        else:
            audio = response.body
            if not audio:
                raise GenerationError("ElevenLabs returned an empty audio response")
        return GenerationResult(
            audio=audio,
            output_format=request.output_format,
            request_id=request_id,
            duration_seconds=_duration(alignment, normalized_alignment, voice_segments),
            alignment=alignment,
            normalized_alignment=normalized_alignment,
            voice_segments=voice_segments,
            metadata={
                "provider": self.provider_id,
                "operation": materialized.operation.value,
                "translation_version": materialized.translation_version,
                "warning_codes": tuple(warning.code for warning in materialized.warnings),
            },
        )

    def stream(self, request: ProviderRequest) -> Iterator[GenerationChunk]:
        if not request.streaming:
            raise CapabilityError("Streaming requires a plan created with streaming=True")
        response: TransportStreamResponse | None = None
        try:
            materialized, response = self._open_stream(request)
            request_id = _header(response.headers, _REQUEST_ID_HEADERS)
            if materialized.operation not in _STREAM_OPERATIONS:
                raise CapabilityError(
                    "ElevenLabs streaming request selected a non-stream operation"
                )
            emitted = False
            if materialized.operation not in _TIMESTAMP_OPERATIONS:
                audio_chunks = (chunk for chunk in response.chunks if chunk)
                for audio, final in _mark_last(audio_chunks):
                    emitted = True
                    yield GenerationChunk(
                        audio=audio,
                        output_format=request.output_format,
                        request_id=request_id,
                        final=final,
                        metadata={
                            "provider": self.provider_id,
                            "operation": materialized.operation.value,
                        },
                    )
            else:
                payloads = _stream_json_objects(response.chunks)
                for payload, final in _mark_last(payloads):
                    emitted = True
                    audio, alignment, normalized_alignment, voice_segments = _timestamp_fields(
                        payload
                    )
                    yield GenerationChunk(
                        audio=audio,
                        output_format=request.output_format,
                        request_id=request_id,
                        final=final,
                        alignment=alignment,
                        normalized_alignment=normalized_alignment,
                        voice_segments=voice_segments,
                        metadata={
                            "provider": self.provider_id,
                            "operation": materialized.operation.value,
                        },
                    )
            if not emitted:
                raise GenerationError("ElevenLabs returned an empty audio stream")
        except OSError as error:
            raise GenerationError(
                "ElevenLabs transport failed",
                context={"provider": self.provider_id, "request_id": request.id},
            ) from error
        finally:
            if response is not None:
                response.close()
