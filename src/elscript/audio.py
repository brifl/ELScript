"""Deterministic audio decoding, timeline assembly, and encoding."""

from __future__ import annotations

import io
import math
import re
import sys
from array import array
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

import av

from .errors import AssemblyError, DecodeError, UnsupportedOutputFormatError

_FORMAT_PATTERN = re.compile(
    r"^(?P<codec>mp3|opus)_(?P<rate>[1-9][0-9]*)_(?P<bitrate>[1-9][0-9]*)$"
    r"|^(?P<raw_codec>pcm|wav|ulaw|alaw)_(?P<raw_rate>[1-9][0-9]*)$"
)
_TARGET_RMS_DBFS = -20.0
_PCM_SAMPLE_BYTES = 2
_ENCODE_FRAME_SAMPLES = 8_192


@dataclass(frozen=True, slots=True)
class AudioFormatSpec:
    name: str
    codec: str
    sample_rate: int
    extension: str
    container: str
    encoder: str
    bitrate: int | None = None


@dataclass(frozen=True, slots=True)
class PCMBuffer:
    """Mono signed 16-bit little-endian PCM at a declared sample rate."""

    data: bytes
    sample_rate: int

    def __post_init__(self) -> None:
        if self.sample_rate < 1:
            raise ValueError("PCM sample_rate must be positive")
        if len(self.data) % _PCM_SAMPLE_BYTES:
            raise ValueError("PCM data must contain complete signed 16-bit samples")

    @property
    def samples(self) -> int:
        return len(self.data) // _PCM_SAMPLE_BYTES

    @property
    def duration_seconds(self) -> float:
        return self.samples / self.sample_rate


@dataclass(frozen=True, slots=True)
class AudioClip:
    data: bytes
    output_format: str

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("audio clips must not be empty")


@dataclass(frozen=True, slots=True)
class Silence:
    duration_seconds: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("silence duration must be finite and positive")


AudioPart = AudioClip | Silence


@dataclass(frozen=True, slots=True)
class AudioAssemblyResult:
    data: bytes
    output_format: str
    extension: str
    duration_seconds: float
    sample_rate: int
    channels: int = 1
    normalization: str | None = None


def parse_output_format(output_format: str) -> AudioFormatSpec:
    """Parse supported ElevenLabs format names into concrete codec settings."""

    match = _FORMAT_PATTERN.fullmatch(output_format)
    if match is None:
        raise UnsupportedOutputFormatError(
            f"Unsupported audio output format {output_format!r}",
            context={"output_format": output_format},
        )
    codec = match.group("codec") or match.group("raw_codec")
    rate_text = match.group("rate") or match.group("raw_rate")
    sample_rate = int(rate_text)
    bitrate_text = match.group("bitrate")
    bitrate = int(bitrate_text) * 1_000 if bitrate_text is not None else None
    settings = {
        "mp3": ("mp3", "mp3", "mp3"),
        "opus": ("ogg", "libopus", "ogg"),
        "pcm": ("s16le", "pcm_s16le", "pcm"),
        "wav": ("wav", "pcm_s16le", "wav"),
        "ulaw": ("mulaw", "pcm_mulaw", "ulaw"),
        "alaw": ("alaw", "pcm_alaw", "alaw"),
    }
    container, encoder, extension = settings[codec]
    return AudioFormatSpec(
        name=output_format,
        codec=codec,
        sample_rate=sample_rate,
        bitrate=bitrate,
        extension=extension,
        container=container,
        encoder=encoder,
    )


def format_extension(output_format: str) -> str:
    return parse_output_format(output_format).extension


def _input_options(spec: AudioFormatSpec) -> dict[str, str] | None:
    if spec.codec not in {"pcm", "ulaw", "alaw"}:
        return None
    return {"sample_rate": str(spec.sample_rate), "channel_layout": "mono"}


def _frame_pcm(frame: av.AudioFrame) -> bytes:
    expected = frame.samples * _PCM_SAMPLE_BYTES
    payload = bytes(frame.planes[0])
    if len(payload) < expected:
        raise DecodeError("Decoded audio frame was shorter than its declared sample count")
    return payload[:expected]


def decode_audio(
    data: bytes,
    output_format: str,
    *,
    target_sample_rate: int | None = None,
) -> PCMBuffer:
    """Decode provider bytes to canonical mono s16 PCM for safe composition."""

    if not data:
        raise DecodeError("Cannot decode empty provider audio")
    spec = parse_output_format(output_format)
    rate = spec.sample_rate if target_sample_rate is None else target_sample_rate
    if rate < 1:
        raise ValueError("target_sample_rate must be positive")
    if spec.codec == "pcm" and len(data) % _PCM_SAMPLE_BYTES:
        raise DecodeError("Raw PCM input contains an incomplete signed 16-bit sample")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    chunks: list[bytes] = []
    try:
        with av.open(
            io.BytesIO(data),
            mode="r",
            format=spec.container,
            options=_input_options(spec),
        ) as container:
            if not container.streams.audio:
                raise DecodeError("Provider audio contains no audio stream")
            for frame in container.decode(audio=0):
                chunks.extend(_frame_pcm(item) for item in resampler.resample(frame))
            chunks.extend(_frame_pcm(item) for item in resampler.resample(None))
    except DecodeError:
        raise
    except (av.FFmpegError, ValueError, EOFError) as error:
        raise DecodeError(
            "Provider audio could not be decoded",
            context={"output_format": output_format},
        ) from error
    pcm = b"".join(chunks)
    if not pcm:
        raise DecodeError("Provider audio decoded to no samples")
    return PCMBuffer(pcm, rate)


def silence_audio(duration_seconds: float, sample_rate: int) -> PCMBuffer:
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise AssemblyError("Silence duration must be finite and positive")
    samples = int(duration_seconds * sample_rate + 0.5)
    if samples < 1:
        raise AssemblyError("Silence duration is shorter than one output sample")
    return PCMBuffer(bytes(samples * _PCM_SAMPLE_BYTES), sample_rate)


def slice_audio(pcm: PCMBuffer, start_seconds: float, end_seconds: float) -> PCMBuffer:
    """Return a timestamp-selected sample range with bounded rounding tolerance."""

    if not math.isfinite(start_seconds) or not math.isfinite(end_seconds):
        raise AssemblyError("Audio slice bounds must be finite")
    if start_seconds < 0 or end_seconds <= start_seconds:
        raise AssemblyError("Audio slice bounds must be positive and increasing")
    tolerance = 1 / pcm.sample_rate
    if end_seconds > pcm.duration_seconds + tolerance:
        raise AssemblyError(
            "Audio slice extends beyond decoded provider audio",
            context={
                "end_seconds": end_seconds,
                "duration_seconds": pcm.duration_seconds,
            },
        )
    start = min(int(start_seconds * pcm.sample_rate + 0.5), pcm.samples)
    end = min(int(end_seconds * pcm.sample_rate + 0.5), pcm.samples)
    if end <= start:
        raise AssemblyError("Audio slice contains no complete samples")
    return PCMBuffer(
        pcm.data[start * _PCM_SAMPLE_BYTES : end * _PCM_SAMPLE_BYTES],
        pcm.sample_rate,
    )


def _concatenate(buffers: Iterable[PCMBuffer], sample_rate: int) -> PCMBuffer:
    materialized = tuple(buffers)
    if not materialized:
        raise AssemblyError("Cannot assemble an output with no audible content")
    if any(buffer.sample_rate != sample_rate for buffer in materialized):
        raise AssemblyError("PCM buffers must share the output sample rate")
    combined = b"".join(buffer.data for buffer in materialized)
    if not combined:
        raise AssemblyError("Cannot assemble an output with no audio samples")
    return PCMBuffer(combined, sample_rate)


def _normalize_rms(pcm: PCMBuffer) -> PCMBuffer:
    samples = array("h")
    samples.frombytes(pcm.data)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return pcm
    square_sum = sum(sample * sample for sample in samples)
    rms = math.sqrt(square_sum / len(samples))
    peak = max(abs(sample) for sample in samples)
    if rms == 0 or peak == 0:
        return pcm
    target_rms = 32_767 * 10 ** (_TARGET_RMS_DBFS / 20)
    factor = min(target_rms / rms, 32_767 / peak)
    normalized = array(
        "h",
        (
            max(-32_768, min(32_767, round(sample * factor)))
            for sample in samples
        ),
    )
    if sys.byteorder != "little":
        normalized.byteswap()
    return PCMBuffer(normalized.tobytes(), pcm.sample_rate)


def _encode_audio(pcm: PCMBuffer, spec: AudioFormatSpec) -> bytes:
    if spec.codec == "pcm":
        return pcm.data
    destination = io.BytesIO()
    try:
        with av.open(destination, mode="w", format=spec.container) as container:
            stream = cast(
                av.AudioStream,
                container.add_stream(spec.encoder, rate=spec.sample_rate),
            )
            stream.layout = "mono"
            if spec.bitrate is not None:
                stream.bit_rate = spec.bitrate
            resampler = av.AudioResampler(
                format=stream.format,
                layout="mono",
                rate=spec.sample_rate,
            )
            offset = 0
            while offset < pcm.samples:
                sample_count = min(_ENCODE_FRAME_SAMPLES, pcm.samples - offset)
                frame = av.AudioFrame(format="s16", layout="mono", samples=sample_count)
                frame.sample_rate = spec.sample_rate
                frame.time_base = Fraction(1, spec.sample_rate)
                frame.pts = offset
                start = offset * _PCM_SAMPLE_BYTES
                frame.planes[0].update(
                    pcm.data[start : start + sample_count * _PCM_SAMPLE_BYTES]
                )
                for converted in resampler.resample(frame):
                    for packet in stream.encode(converted):
                        container.mux(packet)
                offset += sample_count
            for converted in resampler.resample(None):
                for packet in stream.encode(converted):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
    except (av.FFmpegError, ValueError, EOFError) as error:
        raise AssemblyError(
            "Assembled audio could not be encoded",
            context={"output_format": spec.name},
        ) from error
    encoded = destination.getvalue()
    if not encoded:
        raise AssemblyError("Audio encoder returned an empty output")
    return encoded


def encode_audio(
    pcm: PCMBuffer,
    output_format: str,
    *,
    normalize_loudness: bool = False,
) -> AudioAssemblyResult:
    """Normalize optionally and encode one canonical PCM timeline."""

    spec = parse_output_format(output_format)
    if pcm.sample_rate != spec.sample_rate:
        raise AssemblyError("PCM sample rate does not match the selected output format")
    effective = _normalize_rms(pcm) if normalize_loudness else pcm
    return AudioAssemblyResult(
        data=_encode_audio(effective, spec),
        output_format=spec.name,
        extension=spec.extension,
        duration_seconds=effective.duration_seconds,
        sample_rate=effective.sample_rate,
        normalization=(f"rms_dbfs:{_TARGET_RMS_DBFS:g}" if normalize_loudness else None),
    )


def assemble_audio(
    parts: Iterable[AudioPart],
    output_format: str,
    *,
    normalize_loudness: bool = False,
) -> AudioAssemblyResult:
    """Decode clips, insert exact sample-count silence, concatenate, and encode."""

    spec = parse_output_format(output_format)
    buffers: list[PCMBuffer] = []
    for part in parts:
        if isinstance(part, AudioClip):
            buffers.append(
                decode_audio(
                    part.data,
                    part.output_format,
                    target_sample_rate=spec.sample_rate,
                )
            )
        else:
            buffers.append(silence_audio(part.duration_seconds, spec.sample_rate))
    return encode_audio(
        _concatenate(buffers, spec.sample_rate),
        output_format,
        normalize_loudness=normalize_loudness,
    )


def assemble_pcm(
    buffers: Iterable[PCMBuffer],
    output_format: str,
    *,
    normalize_loudness: bool = False,
) -> AudioAssemblyResult:
    """Concatenate already-decoded clips and encode one output artifact."""

    spec = parse_output_format(output_format)
    return encode_audio(
        _concatenate(buffers, spec.sample_rate),
        output_format,
        normalize_loudness=normalize_loudness,
    )
