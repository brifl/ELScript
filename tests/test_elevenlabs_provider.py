from __future__ import annotations

import base64
import json
from dataclasses import replace

import pytest

from elscript.compiler import compile_document
from elscript.config import resolve_config
from elscript.errors import (
    AuthenticationError,
    CapabilityError,
    ELScriptError,
    GenerationError,
    ProviderAccountError,
    RateLimitError,
    UnsupportedModelFeatureError,
)
from elscript.loading import load_document
from elscript.planner import plan_render
from elscript.providers.base import ProviderRequest
from elscript.providers.elevenlabs import (
    ElevenLabsProvider,
    TransportRequest,
    TransportResponse,
)
from elscript.providers.elevenlabs_prompt import elevenlabs_capabilities, prepare_elevenlabs
from elscript.validation import validate_document


class RecordingTransport:
    def __init__(self, *responses: TransportResponse) -> None:
        self.responses = list(responses)
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


class FailingTransport:
    def send(self, request: TransportRequest) -> TransportResponse:
        raise OSError("socket failed and echoed a value that must remain private")


def _planned_request(
    *,
    mode: str = "speech",
    timestamps: bool = False,
    enable_logging: bool = True,
    api: dict[str, object] | None = None,
) -> ProviderRequest:
    script: list[dict[str, object]] = (
        [{"MARA": "One"}, {"ORION": "Two"}] if mode == "dialogue" else [{"MARA": "One"}]
    )
    document = validate_document(
        load_document(
            document={
                "elscript": "1.0",
                "render": {
                    "mode": mode,
                    "timestamps": timestamps,
                    "enable_logging": enable_logging,
                    "seed": 42,
                    "text_normalization": "off",
                    "api": api or {},
                },
                "meta": {"language": "en"},
                "characters": {
                    "MARA": {"voice_id": "mara/voice"},
                    "ORION": {"voice_id": "orion"},
                },
                "pronunciation": {"dictionaries": [{"id": "names", "version_id": "v7"}]},
                "scenes": [{"id": "scene", "script": script}],
            }
        )
    )
    config = resolve_config(document, process_env={})
    compiled = compile_document(document, config)
    translation = prepare_elevenlabs(compiled, document.pronunciation)
    return plan_render(
        compiled,
        config,
        elevenlabs_capabilities(),
        dictionaries=translation.dictionary_locators,
        prepared_segments=translation.prepared_segments,
    ).requests[0]


def _response(*, status: int = 200, body: bytes = b"audio") -> TransportResponse:
    return TransportResponse(status=status, headers={"Request-ID": "provider-request"}, body=body)


def _timestamp_body(*, dialogue: bool = False, audio: bytes = b"timed-audio") -> bytes:
    payload: dict[str, object] = {
        "audio_base64": base64.b64encode(audio).decode(),
        "alignment": {
            "characters": ["O", "n", "e"],
            "character_start_times_seconds": [0, 0.1, 0.2],
            "character_end_times_seconds": [0.1, 0.2, 0.3],
        },
        "normalized_alignment": {
            "characters": ["1"],
            "character_start_times_seconds": [0],
            "character_end_times_seconds": [0.3],
        },
    }
    if dialogue:
        payload["voice_segments"] = [
            {
                "voice_id": "mara/voice",
                "start_time_seconds": 0,
                "end_time_seconds": 0.15,
                "character_start_index": 0,
                "character_end_index": 1,
                "dialogue_input_index": 0,
            },
            {
                "voice_id": "orion",
                "start_time_seconds": 0.15,
                "end_time_seconds": 0.3,
                "character_start_index": 1,
                "character_end_index": 3,
                "dialogue_input_index": 1,
            },
        ]
    return json.dumps(payload).encode()


def test_speech_request_sends_every_material_option_and_normalizes_audio() -> None:
    planned = _planned_request(
        api={
            "voice_settings": {"stability": 0.4, "speed": 0.9},
            "previous_text": "Before",
            "next_request_ids": ["next-1", "next-2"],
        }
    )
    transport = RecordingTransport(_response())
    provider = ElevenLabsProvider("test-secret", transport=transport)

    result = provider.generate(planned)

    assert result.audio == b"audio"
    assert result.request_id == "provider-request"
    assert result.output_format == "mp3_44100_128"
    assert result.metadata["operation"] == "create_speech"
    sent = transport.requests[0]
    assert sent.method == "POST"
    assert sent.url == (
        "https://api.elevenlabs.io/v1/text-to-speech/mara%2Fvoice"
        "?output_format=mp3_44100_128&enable_logging=true"
    )
    assert sent.headers["xi-api-key"] == "test-secret"
    assert "test-secret" not in repr(sent)
    assert json.loads(sent.body) == {
        "model_id": "eleven_v3",
        "pronunciation_dictionary_locators": [
            {"pronunciation_dictionary_id": "names", "version_id": "v7"}
        ],
        "seed": 42,
        "apply_text_normalization": "off",
        "language_code": "en",
        "text": "One",
        "apply_language_text_normalization": False,
        "voice_settings": {"stability": 0.4, "speed": 0.9},
        "previous_text": "Before",
        "next_request_ids": ["next-1", "next-2"],
    }


@pytest.mark.parametrize(
    ("mode", "timestamps", "expected_path"),
    [
        ("speech", False, "/v1/text-to-speech/mara%2Fvoice"),
        ("speech", True, "/v1/text-to-speech/mara%2Fvoice/with-timestamps"),
        ("dialogue", False, "/v1/text-to-dialogue"),
        ("dialogue", True, "/v1/text-to-dialogue/with-timestamps"),
    ],
)
def test_create_operations_use_the_documented_endpoint(
    mode: str,
    timestamps: bool,
    expected_path: str,
) -> None:
    planned = _planned_request(mode=mode, timestamps=timestamps)
    body = _timestamp_body(dialogue=mode == "dialogue") if timestamps else b"audio"
    transport = RecordingTransport(_response(body=body))

    ElevenLabsProvider("key", transport=transport).generate(planned)

    assert transport.requests[0].url.startswith(f"https://api.elevenlabs.io{expected_path}?")


def test_timestamped_dialogue_metadata_is_normalized() -> None:
    planned = _planned_request(mode="dialogue", timestamps=True, api={"settings": {}})
    transport = RecordingTransport(_response(body=_timestamp_body(dialogue=True)))

    result = ElevenLabsProvider("key", transport=transport).generate(planned)

    assert result.audio == b"timed-audio"
    assert result.duration_seconds == 0.3
    assert result.alignment is not None
    assert result.alignment.characters == ("O", "n", "e")
    assert result.alignment.start_seconds == (0.0, 0.1, 0.2)
    assert result.normalized_alignment is not None
    assert result.normalized_alignment.characters == ("1",)
    assert [(item.voice_id, item.part_index) for item in result.voice_segments] == [
        ("mara/voice", 0),
        ("orion", 1),
    ]
    assert [item.character_end_index for item in result.voice_segments] == [1, 3]
    assert json.loads(transport.requests[0].body)["inputs"] == [
        {"text": "One", "voice_id": "mara/voice"},
        {"text": "Two", "voice_id": "orion"},
    ]


@pytest.mark.parametrize(
    ("status", "provider_code", "error_type"),
    [
        (401, "invalid_api_key", AuthenticationError),
        (429, "concurrent_limit_exceeded", RateLimitError),
        (402, "subscription_required", ProviderAccountError),
        (422, "model_not_found", CapabilityError),
        (500, "internal_error", GenerationError),
    ],
)
def test_provider_failures_map_to_stable_safe_errors(
    status: int,
    provider_code: str,
    error_type: type[ELScriptError],
) -> None:
    credential = "live-secret-value"
    response = _response(
        status=status,
        body=json.dumps(
            {
                "detail": {
                    "status": provider_code,
                    "message": f"failure echoed {credential}",
                }
            }
        ).encode(),
    )
    provider = ElevenLabsProvider(credential, transport=RecordingTransport(response))

    with pytest.raises(error_type) as caught:
        provider.generate(_planned_request())

    rendered = str(caught.value)
    assert credential not in rendered
    assert "<redacted>" in rendered
    assert caught.value.code == error_type.default_code


def test_request_stitching_is_bounded_and_rejected_in_zero_retention_mode() -> None:
    too_many = _planned_request(api={"previous_request_ids": ["1", "2", "3", "4"]})
    disabled = _planned_request(
        enable_logging=False,
        api={"previous_request_ids": ["request-before"]},
    )

    for planned, message in (
        (too_many, "at most 3"),
        (disabled, "zero-retention"),
    ):
        transport = RecordingTransport()
        provider = ElevenLabsProvider("key", transport=transport)
        with pytest.raises((CapabilityError, UnsupportedModelFeatureError), match=message):
            provider.generate(planned)
        assert transport.requests == []


def test_missing_credential_and_malformed_provider_data_fail_before_false_success() -> None:
    planned = _planned_request(timestamps=True)
    no_call = RecordingTransport()
    with pytest.raises(AuthenticationError, match="API key"):
        ElevenLabsProvider(None, transport=no_call).generate(planned)
    assert no_call.requests == []

    invalid = RecordingTransport(_response(body=b'{"audio_base64":"not base64"}'))
    with pytest.raises(GenerationError, match="invalid audio_base64"):
        ElevenLabsProvider("key", transport=invalid).generate(planned)


def test_malformed_alignment_and_transport_failures_are_stable_generation_errors() -> None:
    planned = _planned_request(timestamps=True)
    malformed = json.loads(_timestamp_body())
    malformed["alignment"]["character_end_times_seconds"] = [0.1]
    transport = RecordingTransport(_response(body=json.dumps(malformed).encode()))

    with pytest.raises(GenerationError, match="inconsistent lengths"):
        ElevenLabsProvider("key", transport=transport).generate(planned)
    with pytest.raises(GenerationError, match="transport failed") as caught:
        ElevenLabsProvider("private-key", transport=FailingTransport()).generate(planned)
    assert "socket failed" not in str(caught.value)
    assert "private-key" not in str(caught.value)


def test_timestamp_stream_chunks_are_translated_without_live_network() -> None:
    planned = replace(_planned_request(mode="dialogue", timestamps=True), streaming=True)
    body = b"\n".join(
        [_timestamp_body(dialogue=True, audio=b"first"), _timestamp_body(audio=b"second")]
    )
    transport = RecordingTransport(_response(body=body))

    chunks = tuple(ElevenLabsProvider("key", transport=transport).stream(planned))

    assert [chunk.audio for chunk in chunks] == [b"first", b"second"]
    assert [chunk.final for chunk in chunks] == [False, True]
    assert "/v1/text-to-dialogue/stream/with-timestamps?" in transport.requests[0].url
    assert chunks[0].voice_segments[1].part_index == 1
