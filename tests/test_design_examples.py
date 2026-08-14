from __future__ import annotations

from pathlib import Path

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
