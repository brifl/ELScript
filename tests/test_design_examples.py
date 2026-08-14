from __future__ import annotations

from pathlib import Path

from elscript.compiler import compile_document
from elscript.config import resolve_config
from elscript.loading import load_document
from elscript.validation import validate_document


def _comprehensive_example() -> str:
    design = (Path(__file__).parents[1] / "DESIGN.md").read_text(encoding="utf-8")
    section = design.split("## 67. Comprehensive example", 1)[1]
    return section.split("```yaml", 1)[1].split("```", 1)[0].strip()


def test_comprehensive_design_example_validation() -> None:
    validated = validate_document(load_document(yaml_text=_comprehensive_example()))

    assert validated.elscript == "1.0"
    assert validated.meta.id == "signal-below"
    assert set(validated.characters) == {"NARRATOR", "ELLIS", "CALYPSO"}
    assert validated.scenes[0].id == "station"
    assert len(validated.scenes[0].script) == 30


def test_comprehensive_design_example_compiler() -> None:
    validated = validate_document(load_document(yaml_text=_comprehensive_example()))
    compiled = compile_document(validated, resolve_config(validated, process_env={}))

    assert compiled.script_id == "signal-below"
    assert len(compiled.scenes) == 1
    assert len(compiled.segments) == 30
    assert compiled.final_character_states["ELLIS"].emotion == "frightened"
    assert compiled.final_character_states["ELLIS"].intensity == 0.72
    assert compiled.final_character_states["ELLIS"].volume == "normal"
    assert compiled.final_character_states["CALYPSO"].emotion == "apprehensive"
    assert compiled.final_character_states["NARRATOR"].emotion == "ominous"
