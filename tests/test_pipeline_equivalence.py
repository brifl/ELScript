from __future__ import annotations

from pathlib import Path

import yaml

from elscript.loading import load_document


def test_source_forms_produce_the_same_canonical_document(tmp_path: Path) -> None:
    document = {
        "elscript": "1.0",
        "meta": {"id": "equivalent"},
        "characters": {"MARA": {"voice_id": "voice-mara"}},
        "scenes": [
            {"id": "later", "order": 20, "script": [{"MARA": "Later."}]},
            {"id": "first", "order": 10, "script": [{"MARA": "First."}]},
        ],
    }
    yaml_text = yaml.safe_dump(document, sort_keys=False)
    source_file = tmp_path / "story.yaml"
    source_file.write_text(yaml_text, encoding="utf-8")
    source_directory = tmp_path / "project"
    source_directory.mkdir()
    (source_directory / "meta.yaml").write_text(
        "elscript: '1.0'\nmeta: {id: equivalent}\n",
        encoding="utf-8",
    )
    (source_directory / "characters.yaml").write_text(
        "characters: {MARA: {voice_id: voice-mara}}\n",
        encoding="utf-8",
    )
    (source_directory / "scenes.yaml").write_text(
        yaml.safe_dump({"scenes": document["scenes"]}, sort_keys=False),
        encoding="utf-8",
    )

    loaded = [
        load_document(source=source_file),
        load_document(source=source_directory),
        load_document(yaml_text=yaml_text),
        load_document(document=document),
    ]

    assert all(result.data == loaded[0].data for result in loaded[1:])
    assert [scene["id"] for scene in loaded[0].data["scenes"]] == ["first", "later"]
