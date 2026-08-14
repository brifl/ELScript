from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from elscript.compiler import compile_document
from elscript.config import EffectiveConfig, resolve_config
from elscript.domain import (
    CompiledScript,
    Diagnostic,
    DiagnosticSeverity,
    PipelinePhase,
)
from elscript.errors import AssemblyError, WriteError
from elscript.loading import load_document
from elscript.manifest import build_manifest, write_manifest
from elscript.output import OutputWriteResult, write_render_outputs
from elscript.planner import RenderPlan, plan_render
from elscript.providers.base import CharacterAlignment, GenerationResult, RequestKind
from elscript.providers.fake import FakeProvider, fake_capabilities
from elscript.validation import validate_document


@dataclass(frozen=True, slots=True)
class _RenderedCase:
    config: EffectiveConfig
    compiled: CompiledScript
    plan: RenderPlan
    results: dict[str, GenerationResult]
    outputs: OutputWriteResult


def _render_case(
    tmp_path: Path,
    output_mode: str,
    *,
    private: bool = False,
    first_text: str = "AB",
    chunking_max: int | None = None,
) -> _RenderedCase:
    document = validate_document(
        load_document(
            document={
                "elscript": "1.0",
                "meta": {"id": "signal-below"},
                "render": {
                    "provider": "fake",
                    "mode": "auto",
                    "output_format": "wav_16000",
                    "timestamps": True,
                },
                "characters": {
                    "MARA": {"voice_id": "mara-voice"},
                    "ORION": {"voice_id": "orion-voice"},
                },
                "scenes": [
                    {
                        "id": "arrival",
                        "title": "Arrival",
                        "script": [
                            {"MARA": first_text},
                            {"ORION": "CD"},
                            {"pause": 0.25},
                            {"marker": "reveal"},
                            {"note": "internal note"},
                            {"MARA": "EF"},
                        ],
                    },
                    {
                        "id": "basement",
                        "script": [{"ORION": "GH"}],
                    },
                ],
                "export": {
                    "mode": output_mode,
                    "manifest": {"include_source_text": not private},
                    "metadata": {
                        "save_request_ids": not private,
                        "save_voice_segments": not private,
                        "save_character_timestamps": not private,
                        "save_normalized_timestamps": not private,
                    },
                },
            }
        )
    )
    config = resolve_config(
        document,
        process_env={},
        credential="credential-secret",
        options=({"chunking": {"max_chars": chunking_max}} if chunking_max is not None else None),
    )
    compiled = compile_document(document, config)
    plan = plan_render(compiled, config, fake_capabilities())
    provider = FakeProvider()
    results = {request.id: provider.generate(request) for request in plan.requests}
    outputs = write_render_outputs(
        compiled,
        plan,
        results,
        tmp_path / output_mode,
        output_format=config.output_format,
    )
    return _RenderedCase(config, compiled, plan, results, outputs)


@pytest.mark.parametrize(
    ("output_mode", "expected_files"),
    [
        ("single", ["signal-below.wav"]),
        ("scene", ["arrival.wav", "basement.wav"]),
        (
            "segment",
            [
                "arrival_0001_mara.wav",
                "arrival_0002_orion.wav",
                "arrival_0003_mara.wav",
                "basement_0004_orion.wav",
            ],
        ),
    ],
)
def test_manifest_reconstructs_every_file_mode(
    tmp_path: Path,
    output_mode: str,
    expected_files: list[str],
) -> None:
    case = _render_case(tmp_path, output_mode)
    warning = Diagnostic(
        code="W-DEMO",
        message="A bounded warning",
        severity=DiagnosticSeverity.WARNING,
        phase=PipelinePhase.PROVIDER_GENERATION,
    )
    manifest = build_manifest(
        case.compiled,
        case.plan,
        case.results,
        case.outputs,
        case.config,
        warnings=(warning,),
        cache_statuses={case.plan.requests[0].id: "miss"},
        render_fingerprints={
            segment.id: f"sha256:{segment.ordinal}" for segment in case.compiled.segments
        },
    )

    assert manifest.manifest_version == "1.0"
    assert [item.path for item in manifest.files] == expected_files
    assert manifest.duration_seconds == pytest.approx(0.65, abs=1 / 16_000)
    assert [scene.duration_seconds for scene in manifest.scenes] == pytest.approx(
        [0.55, 0.1], abs=1 / 16_000
    )
    assert len(manifest.segments) == 4
    assert len(manifest.provider_requests) == 3
    assert manifest.provider_requests[0].kind == RequestKind.DIALOGUE.value
    assert manifest.provider_requests[0].cache_status == "miss"
    assert [item.cache_status for item in manifest.provider_requests[1:]] == [
        "not_configured",
        "not_configured",
    ]
    assert manifest.warnings[0].code == "W-DEMO"
    assert all(item.render_request_ids for item in manifest.segments)
    assert all(item.provider_request_ids for item in manifest.segments)
    assert all(item.render_fingerprint is not None for item in manifest.segments)
    if output_mode == "segment":
        assert [item.file for item in manifest.segments] == expected_files
        assert [item.file_start_seconds for item in manifest.segments] == [0.0] * 4


def test_timeline_and_provider_metadata_translate_across_request_boundaries(
    tmp_path: Path,
) -> None:
    case = _render_case(tmp_path, "segment")
    manifest = build_manifest(
        case.compiled,
        case.plan,
        case.results,
        case.outputs,
        case.config,
    )

    assert [(item.sequence, item.type) for item in manifest.timeline] == [
        (1, "speech"),
        (2, "speech"),
        (3, "pause"),
        (4, "marker"),
        (5, "note"),
        (6, "speech"),
        (7, "speech"),
    ]
    pause, marker, note = manifest.timeline[2:5]
    assert (pause.time_seconds, pause.end_seconds, pause.duration_seconds) == pytest.approx(
        (0.2, 0.45, 0.25), abs=1 / 16_000
    )
    assert marker.name == "reveal"
    assert marker.time_seconds == pytest.approx(0.45, abs=1 / 16_000)
    assert note.text == "internal note"
    assert len(manifest.voice_segments) == 2
    assert [item.segment_id for item in manifest.voice_segments] == [
        case.compiled.segments[0].id,
        case.compiled.segments[1].id,
    ]
    assert [item.timeline_start_seconds for item in manifest.voice_segments] == pytest.approx(
        [0.0, 0.1], abs=1 / 16_000
    )
    assert all(item.file_start_seconds == 0.0 for item in manifest.voice_segments)

    character = [item for item in manifest.alignments if item.kind == "character"]
    assert ["".join(item.characters) for item in character] == ["AB", "CD", "EF", "GH"]
    assert [item.timeline_start_seconds[0] for item in character] == pytest.approx(
        [0.0, 0.1, 0.45, 0.55], abs=1 / 16_000
    )
    assert all(item.file_start_seconds is not None for item in character)
    for item in character:
        assert item.file_start_seconds is not None
        assert item.file_start_seconds[0] == 0.0


def test_split_logical_segment_alignment_uses_cumulative_file_offsets(tmp_path: Path) -> None:
    case = _render_case(
        tmp_path,
        "segment",
        first_text="ABCDEFGHIJ",
        chunking_max=4,
    )
    manifest = build_manifest(
        case.compiled,
        case.plan,
        case.results,
        case.outputs,
        case.config,
    )
    first_segment = manifest.segments[0]
    character = [
        item
        for item in manifest.alignments
        if item.kind == "character" and item.segment_id == first_segment.id
    ]

    assert len(first_segment.render_request_ids) == 3
    assert first_segment.duration_seconds == pytest.approx(0.3, abs=1 / 16_000)
    assert ["".join(item.characters) for item in character] == ["ABCD", "EFGH", "IJ"]
    assert [item.file_start_seconds[0] for item in character if item.file_start_seconds] == (
        pytest.approx([0.0, 0.1, 0.2], abs=1 / 16_000)
    )


def test_private_manifest_omits_authored_and_provider_metadata_and_redacts_secrets(
    tmp_path: Path,
) -> None:
    case = _render_case(tmp_path, "single", private=True)
    warning = Diagnostic(
        code="W-PRIVATE",
        message="Provider echoed credential-secret",
        severity=DiagnosticSeverity.WARNING,
        phase=PipelinePhase.PROVIDER_GENERATION,
        context={
            "headers": {"authorization": "Bearer warning-secret"},
            "nested": {"provider_api_key": "context-secret"},
            "detail": "credential-secret appeared in a non-sensitive field",
        },
    )
    manifest = build_manifest(
        case.compiled,
        case.plan,
        case.results,
        case.outputs,
        case.config,
        warnings=(warning,),
    )
    serialized = manifest.to_json()

    assert all(item.source_text is None for item in manifest.segments)
    assert all(not item.provider_request_ids for item in manifest.segments)
    assert all(item.provider_request_id is None for item in manifest.provider_requests)
    assert not manifest.alignments
    assert not manifest.voice_segments
    for secret in (
        "AB",
        "internal note",
        "credential-secret",
        "warning-secret",
        "context-secret",
    ):
        assert secret not in serialized
    assert "<redacted>" in serialized


def test_manifest_write_is_contained_deterministic_and_never_overwrites(
    tmp_path: Path,
) -> None:
    case = _render_case(tmp_path, "single")
    manifest = build_manifest(
        case.compiled,
        case.plan,
        case.results,
        case.outputs,
        case.config,
    )

    path = write_manifest(manifest, case.outputs.files[0].parent)

    assert path.name == "signal-below.manifest.json"
    assert path.parent == case.outputs.files[0].parent.resolve()
    assert json.loads(path.read_text(encoding="utf-8")) == manifest.to_dict()
    with pytest.raises(WriteError, match="Refusing to overwrite"):
        write_manifest(manifest, case.outputs.files[0].parent)


def test_manifest_rejects_malformed_provider_timing_metadata(tmp_path: Path) -> None:
    case = _render_case(tmp_path, "segment")
    dialogue = case.plan.requests[0]
    result = case.results[dialogue.id]
    malformed_alignment = dict(case.results)
    malformed_alignment[dialogue.id] = replace(
        result,
        alignment=CharacterAlignment(("A",), (), ()),
    )

    with pytest.raises(AssemblyError, match="different lengths"):
        build_manifest(
            case.compiled,
            case.plan,
            malformed_alignment,
            case.outputs,
            case.config,
        )

    repeated_voice = dict(case.results)
    repeated_voice[dialogue.id] = replace(
        result,
        voice_segments=(result.voice_segments[0], result.voice_segments[0]),
    )
    with pytest.raises(AssemblyError, match="repeats a dialogue input"):
        build_manifest(
            case.compiled,
            case.plan,
            repeated_voice,
            case.outputs,
            case.config,
        )

    reversed_voice = dict(case.results)
    reversed_voice[dialogue.id] = replace(
        result,
        voice_segments=(
            replace(
                result.voice_segments[1],
                start_seconds=0.0,
                end_seconds=0.1,
            ),
            replace(
                result.voice_segments[0],
                start_seconds=0.1,
                end_seconds=0.2,
            ),
        ),
    )
    with pytest.raises(AssemblyError, match="does not follow dialogue input order"):
        build_manifest(
            case.compiled,
            case.plan,
            reversed_voice,
            case.outputs,
            case.config,
        )
