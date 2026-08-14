from __future__ import annotations

import math
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from elscript.audio import PCMBuffer, decode_audio, encode_audio
from elscript.compiler import compile_document
from elscript.config import resolve_config
from elscript.domain import CompiledScript
from elscript.errors import AssemblyError, FilenameCollisionError, WriteError
from elscript.loading import load_document
from elscript.output import (
    build_output_targets,
    sanitize_filename_component,
    segment_output_filename,
    write_render_outputs,
)
from elscript.planner import RenderPlan, plan_render
from elscript.providers.base import GenerationResult, VoiceSegmentMetadata
from elscript.providers.elevenlabs_prompt import elevenlabs_capabilities, prepare_elevenlabs
from elscript.schema import ELScriptDocument
from elscript.validation import validate_document


def _pipeline(
    output_mode: str,
    *,
    render_mode: str = "speech",
    script: list[dict[str, object]] | None = None,
) -> tuple[ELScriptDocument, CompiledScript, RenderPlan]:
    document = validate_document(
        load_document(
            document={
                "elscript": "1.0",
                "meta": {"id": "signal-below"},
                "render": {
                    "mode": render_mode,
                    "output_format": "wav_16000",
                },
                "characters": {
                    "MARA": {"voice_id": "mara-voice"},
                    "ORION": {"voice_id": "orion-voice"},
                },
                "scenes": script
                or [
                    {
                        "id": "arrival",
                        "script": [
                            {"MARA": "One"},
                            {"pause": 0.25},
                            {"ORION": "Two"},
                        ],
                    },
                    {"id": "basement", "script": [{"MARA": "Three"}]},
                ],
                "export": {"mode": output_mode},
            }
        )
    )
    config = resolve_config(document, process_env={})
    compiled = compile_document(document, config)
    translation = prepare_elevenlabs(compiled, document.pronunciation)
    plan = plan_render(
        compiled,
        config,
        elevenlabs_capabilities(),
        dictionaries=translation.dictionary_locators,
        prepared_segments=translation.prepared_segments,
    )
    return document, compiled, plan


def _tone(seconds: float = 0.1, *, amplitude: int = 4_000) -> PCMBuffer:
    rate = 16_000
    count = int(rate * seconds)
    return PCMBuffer(
        b"".join(
            struct.pack(
                "<h",
                round(amplitude * math.sin(2 * math.pi * 440 * index / rate)),
            )
            for index in range(count)
        ),
        rate,
    )


def _speech_results(plan: RenderPlan) -> dict[str, GenerationResult]:
    encoded = encode_audio(_tone(), "wav_16000")
    return {
        request.id: GenerationResult(
            audio=encoded.data,
            output_format="wav_16000",
            request_id=f"provider-{request.id}",
        )
        for request in plan.requests
    }


def test_single_and_scene_outputs_preserve_timeline_and_pause_duration(tmp_path: Path) -> None:
    _, compiled, single_plan = _pipeline("single")
    single = write_render_outputs(
        compiled,
        single_plan,
        _speech_results(single_plan),
        tmp_path / "single",
        output_format="wav_16000",
        normalize_loudness=True,
    )

    assert [path.name for path in single.files] == ["signal-below.wav"]
    assert single.normalization == "rms_dbfs:-20"
    assert decode_audio(single.files[0].read_bytes(), "wav_16000").duration_seconds == (
        pytest.approx(0.55, abs=1 / 16_000)
    )

    _, compiled, scene_plan = _pipeline("scene")
    scene = write_render_outputs(
        compiled,
        scene_plan,
        _speech_results(scene_plan),
        tmp_path / "scene",
        output_format="wav_16000",
    )
    assert [path.name for path in scene.files] == ["arrival.wav", "basement.wav"]
    assert [artifact.duration_seconds for artifact in scene.artifacts] == pytest.approx(
        [0.45, 0.1], abs=1 / 16_000
    )


def test_segment_mode_writes_only_audible_segments_with_global_names(tmp_path: Path) -> None:
    _, compiled, plan = _pipeline("segment")

    written = write_render_outputs(
        compiled,
        plan,
        _speech_results(plan),
        tmp_path,
        output_format="wav_16000",
    )

    assert [path.name for path in written.files] == [
        "arrival_0001_mara.wav",
        "arrival_0002_orion.wav",
        "basement_0003_mara.wav",
    ]
    assert all(artifact.duration_seconds == pytest.approx(0.1) for artifact in written.artifacts)
    assert len(tuple(tmp_path.iterdir())) == 3


def test_dialogue_voice_segments_extract_one_valid_file_per_logical_segment(
    tmp_path: Path,
) -> None:
    _, compiled, plan = _pipeline(
        "segment",
        render_mode="dialogue",
        script=[{"id": "scene", "script": [{"MARA": "One"}, {"ORION": "Two"}]}],
    )
    assert len(plan.requests) == 1
    audio = encode_audio(_tone(0.2), "wav_16000")
    request = plan.requests[0]
    results = {
        request.id: GenerationResult(
            audio=audio.data,
            output_format="wav_16000",
            voice_segments=(
                VoiceSegmentMetadata("mara-voice", 0.0, 0.1, part_index=0),
                VoiceSegmentMetadata("orion-voice", 0.1, 0.2, part_index=1),
            ),
        )
    }

    written = write_render_outputs(
        compiled,
        plan,
        results,
        tmp_path,
        output_format="wav_16000",
    )

    assert [path.name for path in written.files] == [
        "scene_0001_mara.wav",
        "scene_0002_orion.wav",
    ]
    assert [
        decode_audio(path.read_bytes(), "wav_16000").duration_seconds
        for path in written.files
    ] == pytest.approx([0.1, 0.1], abs=1 / 16_000)


def test_sanitization_is_contained_collision_safe_and_portable() -> None:
    _, compiled, _ = _pipeline("scene")
    first, second = compiled.scenes
    unsafe = replace(
        compiled,
        script_id="../../outside",
        scenes=(replace(first, id="../AUX"), replace(second, id="..\\AUX")),
    )

    assert build_output_targets(unsafe, "single", "wav_16000")[0].filename == "outside.wav"
    assert sanitize_filename_component("CON") == "_CON"
    with pytest.raises(FilenameCollisionError, match="not unique"):
        build_output_targets(unsafe, "scene", "wav_16000")


def test_segment_padding_widens_above_9999_and_preserves_lexical_order() -> None:
    _, compiled, _ = _pipeline("segment")
    segment = compiled.segments[0]
    before = segment_output_filename(
        replace(segment, ordinal=9_999),
        max_ordinal=10_000,
        output_format="wav_16000",
    )
    after = segment_output_filename(
        replace(segment, ordinal=10_000),
        max_ordinal=10_000,
        output_format="wav_16000",
    )

    assert before == "arrival_09999_mara.wav"
    assert after == "arrival_10000_mara.wav"
    assert sorted([after, before]) == [before, after]


def test_existing_files_and_incomplete_dialogue_metadata_fail_without_overwrite(
    tmp_path: Path,
) -> None:
    _, compiled, plan = _pipeline("single")
    results = _speech_results(plan)
    first = write_render_outputs(
        compiled,
        plan,
        results,
        tmp_path,
        output_format="wav_16000",
    )
    original = first.files[0].read_bytes()

    with pytest.raises(WriteError, match="Refusing to overwrite"):
        write_render_outputs(
            compiled,
            plan,
            results,
            tmp_path,
            output_format="wav_16000",
        )
    assert first.files[0].read_bytes() == original

    _, dialogue_compiled, dialogue_plan = _pipeline(
        "segment",
        render_mode="dialogue",
        script=[{"id": "scene", "script": [{"MARA": "One"}, {"ORION": "Two"}]}],
    )
    request = dialogue_plan.requests[0]
    encoded = encode_audio(_tone(0.2), "wav_16000")
    incomplete = {
        request.id: GenerationResult(
            audio=encoded.data,
            output_format="wav_16000",
            voice_segments=(
                VoiceSegmentMetadata("mara-voice", 0.0, 0.1, part_index=0),
            ),
        )
    }
    with pytest.raises(AssemblyError, match="omitted planned inputs"):
        write_render_outputs(
            dialogue_compiled,
            dialogue_plan,
            incomplete,
            tmp_path / "incomplete",
            output_format="wav_16000",
        )


def test_output_directory_cannot_be_mistaken_for_a_destination_filename(
    tmp_path: Path,
) -> None:
    _, compiled, plan = _pipeline("single")
    mistaken_filename = tmp_path / "story.wav"

    with pytest.raises(WriteError, match="must be a directory"):
        write_render_outputs(
            compiled,
            plan,
            _speech_results(plan),
            mistaken_filename,
            output_format="wav_16000",
        )
    assert not mistaken_filename.exists()
