from __future__ import annotations

from pathlib import Path

import pytest

from elscript.errors import MergeConflictError
from elscript.loading import load_document


def test_compatible_mappings_merge_and_tags_form_stable_union(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "meta: {id: demo, tags: [one, shared]}\ncharacters: {MARA: {voice_id: abc}}\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        "meta: {tags: [shared, two]}\ncharacters: {MARA: {defaults: {emotion: calm}}}\n",
        encoding="utf-8",
    )

    merged = load_document(source=tmp_path)

    assert merged.data["meta"] == {"id": "demo", "tags": ["one", "shared", "two"]}
    assert merged.data["characters"] == {
        "MARA": {"voice_id": "abc", "defaults": {"emotion": "calm"}}
    }


def test_conflict_reports_logical_path_and_both_sources(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("characters: {MARA: {voice_id: first}}\n", encoding="utf-8")
    second.write_text("characters: {MARA: {voice_id: second}}\n", encoding="utf-8")

    with pytest.raises(MergeConflictError) as raised:
        load_document(source=tmp_path)

    rendered = str(raised.value)
    assert "$.characters.MARA.voice_id" in rendered
    assert str(first) in rendered
    assert str(second) in rendered


def test_scene_ids_are_unique_across_files(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("scenes: [{id: duplicate, script: []}]\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("scenes: [{id: duplicate, script: []}]\n", encoding="utf-8")

    with pytest.raises(MergeConflictError, match="Duplicate scene id 'duplicate'"):
        load_document(source=tmp_path)


def test_scenes_order_by_explicit_order_then_normalized_source_and_position(
    tmp_path: Path,
) -> None:
    (tmp_path / "z.yaml").write_text(
        "scenes:\n  - {id: z-implicit, script: []}\n  - {id: first, order: 10, script: []}\n",
        encoding="utf-8",
    )
    (tmp_path / "a.yaml").write_text(
        "scenes:\n  - {id: second, order: 20, script: []}\n  - {id: a-implicit, script: []}\n",
        encoding="utf-8",
    )

    merged = load_document(source=tmp_path)

    assert [scene["id"] for scene in merged.data["scenes"]] == [
        "first",
        "second",
        "a-implicit",
        "z-implicit",
    ]


def test_pronunciation_dictionary_duplicates_must_be_compatible(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "pronunciation: {dictionaries: [{id: dictionary, version_id: one}]}\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        "pronunciation: {dictionaries: [{id: dictionary, version_id: two}]}\n",
        encoding="utf-8",
    )

    with pytest.raises(MergeConflictError, match="pronunciation.dictionaries"):
        load_document(source=tmp_path)


def test_non_special_lists_conflict_instead_of_silently_combining(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "presets: {calm: {delivery: [warm]}}\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        "presets: {calm: {delivery: [restrained]}}\n",
        encoding="utf-8",
    )

    with pytest.raises(MergeConflictError, match=r"\$\.presets\.calm\.delivery"):
        load_document(source=tmp_path)
