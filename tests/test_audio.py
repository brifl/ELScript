from __future__ import annotations

import math
import struct

import pytest

from elscript.audio import (
    AudioClip,
    PCMBuffer,
    Silence,
    assemble_audio,
    decode_audio,
    encode_audio,
    format_extension,
    slice_audio,
)
from elscript.errors import AssemblyError, DecodeError, UnsupportedOutputFormatError


def _tone(*, seconds: float = 0.1, rate: int = 16_000, amplitude: int = 4_000) -> PCMBuffer:
    samples = int(seconds * rate)
    data = b"".join(
        struct.pack("<h", round(amplitude * math.sin(2 * math.pi * 440 * index / rate)))
        for index in range(samples)
    )
    return PCMBuffer(data, rate)


def _rms(pcm: PCMBuffer) -> float:
    samples = struct.unpack(f"<{pcm.samples}h", pcm.data)
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def test_wav_clips_and_explicit_silence_assemble_in_sample_exact_order() -> None:
    tone = _tone()
    encoded = encode_audio(tone, "wav_16000")

    result = assemble_audio(
        [
            AudioClip(encoded.data, encoded.output_format),
            Silence(0.25),
            AudioClip(encoded.data, encoded.output_format),
        ],
        "wav_16000",
    )
    decoded = decode_audio(result.data, result.output_format)

    assert result.extension == "wav"
    assert result.duration_seconds == pytest.approx(0.45, abs=1 / 16_000)
    assert decoded.duration_seconds == pytest.approx(0.45, abs=1 / 16_000)
    silence_start = tone.samples * 2
    silence_end = silence_start + int(0.25 * 16_000) * 2
    assert decoded.data[silence_start:silence_end] == bytes(silence_end - silence_start)
    assert decoded.data[: tone.samples * 2] != bytes(tone.samples * 2)
    assert decoded.data[silence_end:] != bytes(tone.samples * 2)


def test_default_mp3_format_is_a_decodable_audio_container() -> None:
    source = _tone(seconds=0.2, rate=44_100)

    encoded = encode_audio(source, "mp3_44100_128")
    decoded = decode_audio(encoded.data, encoded.output_format)

    assert encoded.data.startswith(b"ID3")
    assert encoded.extension == "mp3"
    assert decoded.duration_seconds == pytest.approx(0.2, abs=0.03)


def test_loudness_normalization_is_deterministic_and_reported() -> None:
    quiet = _tone(amplitude=200)

    first = encode_audio(quiet, "wav_16000", normalize_loudness=True)
    second = encode_audio(quiet, "wav_16000", normalize_loudness=True)
    normalized = decode_audio(first.data, first.output_format)

    assert first.data == second.data
    assert first.normalization == "rms_dbfs:-20"
    assert _rms(normalized) > _rms(quiet) * 10


@pytest.mark.parametrize(
    ("output_format", "extension", "sample_rate"),
    [
        ("mp3_44100_128", "mp3", 44_100),
        ("opus_48000_64", "ogg", 48_000),
        ("pcm_16000", "pcm", 16_000),
        ("wav_44100", "wav", 44_100),
        ("ulaw_8000", "ulaw", 8_000),
        ("alaw_8000", "alaw", 8_000),
    ],
)
def test_format_names_map_to_deterministic_extensions(
    output_format: str,
    extension: str,
    sample_rate: int,
) -> None:
    encoded = encode_audio(_tone(rate=sample_rate), output_format)
    decoded = decode_audio(encoded.data, output_format)

    assert format_extension(output_format) == extension
    assert decoded.duration_seconds == pytest.approx(0.1, abs=0.03)


def test_decode_and_slice_fail_closed_on_invalid_audio_or_bounds() -> None:
    with pytest.raises(DecodeError, match="could not be decoded"):
        decode_audio(b"not a wave", "wav_16000")
    with pytest.raises(UnsupportedOutputFormatError, match="Unsupported"):
        format_extension("made_up_123")

    tone = _tone()
    with pytest.raises(AssemblyError, match="beyond"):
        slice_audio(tone, 0.05, 2.0)
