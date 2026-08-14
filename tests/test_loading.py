from __future__ import annotations

from pathlib import Path

import pytest

from elscript.errors import InputError, InvalidYamlError, SourceNotFoundError
from elscript.loading import discover_yaml_files, load_document


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"source": "story.yaml", "yaml_text": "{}"},
        {"source": "story.yaml", "yaml_text": "{}", "document": {}},
    ],
)
def test_exactly_one_source_form_is_required(kwargs: dict[str, object]) -> None:
    with pytest.raises(InputError, match="Exactly one"):
        load_document(**kwargs)  # type: ignore[arg-type]


def test_yaml_is_loaded_safely_and_requires_mapping_root() -> None:
    with pytest.raises(InvalidYamlError) as raised:
        load_document(yaml_text="value: [unterminated")
    assert raised.value.location is not None
    assert raised.value.location.line == 1

    with pytest.raises(InvalidYamlError):
        load_document(yaml_text="!!python/object/apply:os.system ['echo unsafe']")

    with pytest.raises(InputError, match="mapping at the document root"):
        load_document(yaml_text="- not\n- a\n- mapping\n")


def test_missing_and_non_yaml_file_sources_are_actionable(tmp_path: Path) -> None:
    with pytest.raises(SourceNotFoundError, match="does not exist"):
        load_document(source=tmp_path / "missing.yaml")

    text_file = tmp_path / "story.txt"
    text_file.write_text("elscript: '1.0'", encoding="utf-8")
    with pytest.raises(InputError, match="must end in .yaml or .yml"):
        load_document(source=text_file)


def test_directory_discovery_is_recursive_sorted_and_excludes_outputs(tmp_path: Path) -> None:
    (tmp_path / "scenes").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "build").mkdir()
    (tmp_path / "generated").mkdir()
    (tmp_path / "scenes" / "020.yml").write_text("meta: {title: second}", encoding="utf-8")
    (tmp_path / "scenes" / "010.yaml").write_text("meta: {title: first}", encoding="utf-8")
    (tmp_path / ".hidden" / "secret.yaml").write_text("ignored: true", encoding="utf-8")
    (tmp_path / "build" / "artifact.yaml").write_text("ignored: true", encoding="utf-8")
    (tmp_path / "generated" / "manifest.yaml").write_text("ignored: true", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    discovered = discover_yaml_files(tmp_path, output_dir=tmp_path / "generated")

    assert [path.relative_to(tmp_path).as_posix() for path in discovered] == [
        "scenes/010.yaml",
        "scenes/020.yml",
    ]


def test_mapping_input_is_copied_and_receives_provenance() -> None:
    original = {"meta": {"id": "example"}, "scenes": []}
    loaded = load_document(document=original)
    original["meta"]["id"] = "mutated"  # type: ignore[index]

    assert loaded.data["meta"]["id"] == "example"  # type: ignore[index]
    assert loaded.provenance["$.meta.id"].source == "<document>"
