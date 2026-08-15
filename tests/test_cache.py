from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import elscript.api as api_module
from elscript import render_document
from elscript.cache import (
    RenderCache,
    cache_root_for_output,
    fingerprint_render_plan,
)
from elscript.compiler import compile_document
from elscript.config import resolve_config
from elscript.errors import DecodeError
from elscript.loading import load_document
from elscript.planner import RenderPlan, plan_render
from elscript.providers.base import DictionaryLocator, GenerationResult, ProviderRequest
from elscript.providers.fake import FakeProvider
from elscript.validation import validate_document


def _document() -> dict[str, object]:
    return {
        "elscript": "1.0",
        "meta": {"id": "cache-story", "title": "Ignored title"},
        "render": {
            "provider": "fake",
            "mode": "speech",
            "model": "fake-model",
            "output_format": "wav_16000",
            "timestamps": True,
            "seed": 17,
            "text_normalization": "off",
            "language_text_normalization": False,
            "api": {"voice_settings": {"stability": 0.4}},
            "chunking": {"preserve_continuity": True},
        },
        "characters": {
            "MARA": {"voice_id": "mara-voice"},
            "ORION": {"voice_id": "orion-voice"},
        },
        "scenes": [
            {
                "id": "one",
                "script": [
                    {"MARA": {"id": "a", "say": "Alpha."}},
                    {"MARA": {"id": "b", "say": "Bravo."}},
                ],
            }
        ],
        "export": {"mode": "segment"},
    }


def _plan(
    document: dict[str, object],
    *,
    credential: str | None = None,
) -> tuple[RenderPlan, bool, bool]:
    validated = validate_document(load_document(document=document))
    config = resolve_config(validated, process_env={}, credential=credential)
    compiled = compile_document(validated, config)
    return (
        plan_render(compiled, config, FakeProvider().describe_capabilities()),
        config.normalize_loudness,
        config.chunking.preserve_continuity,
    )


def _fingerprints(
    document: dict[str, object],
    *,
    credential: str | None = None,
) -> tuple[str, ...]:
    plan, normalize_loudness, preserve_continuity = _plan(
        document,
        credential=credential,
    )
    fingerprints = fingerprint_render_plan(
        plan,
        normalize_loudness=normalize_loudness,
        preserve_continuity=preserve_continuity,
    )
    return tuple(fingerprints.requests[request.id] for request in plan.requests)


def test_fingerprints_cover_material_inputs_and_exclude_non_audio_state() -> None:
    document = _document()
    baseline = _fingerprints(document, credential="first-secret")

    unrelated = deepcopy(document)
    unrelated["meta"] = {
        "id": "different-output-name",
        "title": "Different title",
        "description": "Unrelated metadata",
    }
    unrelated["export"] = {
        "mode": "scene",
        "manifest": {"include_source_text": False},
    }
    assert _fingerprints(unrelated, credential="second-secret") == baseline

    for mutate in (
        lambda value: value["scenes"][0]["script"][0]["MARA"].update({"say": "Changed prompt."}),
        lambda value: value["characters"]["MARA"].update({"voice_id": "other-voice"}),
        lambda value: value["render"].update({"model": "other-model"}),
        lambda value: value["render"].update({"seed": 99}),
        lambda value: value["meta"].update({"language": "fr"}),
        lambda value: value["render"].update({"text_normalization": "on"}),
        lambda value: value["render"]["api"]["voice_settings"].update({"stability": 0.8}),
    ):
        changed = deepcopy(document)
        mutate(changed)
        assert _fingerprints(changed) != baseline

    plan, normalize_loudness, preserve_continuity = _plan(document)
    request = plan.requests[0]
    with_dictionary = replace(
        request,
        dictionary_locators=(DictionaryLocator("dictionary", "v2"),),
    )
    translated_part = replace(request.parts[0], translation_version="adapter-v2")
    translated = replace(request, parts=(translated_part,))
    for changed_plan in (
        replace(plan, requests=(with_dictionary, *plan.requests[1:])),
        replace(plan, requests=(translated, *plan.requests[1:])),
        replace(plan, capability_version="fake-adapter-v2"),
    ):
        changed = fingerprint_render_plan(
            changed_plan,
            normalize_loudness=normalize_loudness,
            preserve_continuity=preserve_continuity,
        )
        assert tuple(changed.requests.values()) != baseline

    normalized = fingerprint_render_plan(
        plan,
        normalize_loudness=True,
        preserve_continuity=preserve_continuity,
    )
    assert tuple(normalized.requests.values()) != baseline


def test_exact_repeat_uses_cache_and_exposes_hits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(api_module, "FakeProvider", lambda: provider)

    first = render_document(_document(), output_dir=tmp_path / "first")
    second = render_document(_document(), output_dir=tmp_path / "second")

    assert len(provider.requests) == 2
    assert (first.cache_hits, first.cache_misses) == (0, 2)
    assert (second.cache_hits, second.cache_misses) == (2, 0)
    assert [path.read_bytes() for path in first.files] == [
        path.read_bytes() for path in second.files
    ]
    assert second.manifest_path is not None
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert [request["cache_status"] for request in manifest["provider_requests"]] == [
        "hit",
        "hit",
    ]
    assert all(segment["render_fingerprint"] for segment in manifest["segments"])


def test_provider_grouping_is_part_of_request_identity() -> None:
    grouped = _document()
    grouped["render"]["mode"] = "auto"
    grouped["scenes"] = [
        {
            "id": "one",
            "script": [
                {"MARA": {"id": "a", "say": "Alpha."}},
                {"ORION": {"id": "b", "say": "Bravo."}},
            ],
        }
    ]
    split = deepcopy(grouped)
    split["scenes"][0]["script"].insert(1, {"marker": "boundary"})

    grouped_fingerprints = set(_fingerprints(grouped))
    split_fingerprints = set(_fingerprints(split))

    assert len(grouped_fingerprints) == 1
    assert len(split_fingerprints) == 2
    assert grouped_fingerprints.isdisjoint(split_fingerprints)


def test_stitching_depth_tracks_each_referenced_neighbor() -> None:
    document = _document()
    document["render"]["chunking"] = {"preserve_continuity": False}
    document["scenes"][0]["script"].extend(
        [
            {"MARA": {"id": "c", "say": "Charlie."}},
            {"MARA": {"id": "d", "say": "Delta."}},
        ]
    )
    plan, normalize_loudness, _ = _plan(document)
    last = replace(
        plan.requests[-1],
        provider_options={"previous_request_ids": ("provider-a", "provider-b")},
    )
    stitched = replace(plan, requests=(*plan.requests[:-1], last))
    before = fingerprint_render_plan(
        stitched,
        normalize_loudness=normalize_loudness,
        preserve_continuity=False,
    )
    second = plan.requests[1]
    changed_part = replace(second.parts[0], text="Changed bravo.")
    changed_second = replace(second, parts=(changed_part,))
    changed = replace(
        stitched,
        requests=(plan.requests[0], changed_second, plan.requests[2], last),
    )
    after = fingerprint_render_plan(
        changed,
        normalize_loudness=normalize_loudness,
        preserve_continuity=False,
    )

    assert before.requests[last.id] != after.requests[last.id]


@pytest.mark.parametrize("damaged", [b"{", b'{"version":1}'])
def test_corrupt_or_incomplete_entry_is_regenerated_and_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damaged: bytes,
) -> None:
    document = _document()
    document["scenes"] = [{"id": "one", "script": [{"MARA": {"id": "a", "say": "Alpha."}}]}]
    provider = FakeProvider()
    monkeypatch.setattr(api_module, "FakeProvider", lambda: provider)
    first = render_document(document, output_dir=tmp_path / "first")
    cache_root = cache_root_for_output((tmp_path / "first").resolve())
    records = tuple(cache_root.glob("*/*.json"))
    assert len(records) == 1
    records[0].write_bytes(damaged)

    repaired = render_document(document, output_dir=tmp_path / "repaired")
    again = render_document(document, output_dir=tmp_path / "again")

    assert len(provider.requests) == 2
    assert (first.cache_misses, repaired.cache_misses, again.cache_hits) == (1, 1, 1)
    assert repaired.manifest_path is not None
    payload = json.loads(repaired.manifest_path.read_text(encoding="utf-8"))
    assert payload["provider_requests"][0]["cache_status"] == "corrupt"


def test_invalid_provider_result_is_not_published_to_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.fake = FakeProvider()

        def describe_capabilities(self):  # type: ignore[no-untyped-def]
            return self.fake.describe_capabilities()

        def generate(self, request: ProviderRequest) -> GenerationResult:
            self.calls += 1
            return GenerationResult(b"not-a-wave", request.output_format)

    document = _document()
    document["scenes"] = [{"id": "one", "script": [{"MARA": {"id": "a", "say": "Alpha."}}]}]
    provider = InvalidProvider()
    monkeypatch.setattr(api_module, "FakeProvider", lambda: provider)

    for output in (tmp_path / "first", tmp_path / "second"):
        with pytest.raises(DecodeError):
            render_document(document, output_dir=output)

    assert provider.calls == 2
    cache_root = cache_root_for_output((tmp_path / "first").resolve())
    assert not tuple(cache_root.glob("*/*.json"))


def test_atomic_records_remain_readable_during_concurrent_replacement(
    tmp_path: Path,
) -> None:
    document = _document()
    document["scenes"] = [{"id": "one", "script": [{"MARA": {"id": "a", "say": "Alpha."}}]}]
    plan, normalize_loudness, preserve_continuity = _plan(document)
    fingerprints = fingerprint_render_plan(
        plan,
        normalize_loudness=normalize_loudness,
        preserve_continuity=preserve_continuity,
    )
    request = plan.requests[0]
    fingerprint = fingerprints.requests[request.id]
    result = FakeProvider().generate(request)
    cache_root = tmp_path / "cache"
    cache = RenderCache(cache_root)
    assert cache.store(fingerprint, result)

    def write_many() -> None:
        writer = RenderCache(cache_root)
        for _ in range(5):
            assert writer.store(fingerprint, result)

    def read_many() -> set[str]:
        reader = RenderCache(cache_root)
        return {
            reader.lookup(fingerprint, output_format=request.output_format).status
            for _ in range(12)
        }

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(write_many) for _ in range(2)]
        readers = [executor.submit(read_many) for _ in range(4)]
        for future in futures:
            future.result()
        statuses = set().union(*(future.result() for future in readers))

    assert statuses == {"hit"}
    assert cache.lookup(fingerprint, output_format=request.output_format).result == replace(
        result,
        metadata={},
    )
