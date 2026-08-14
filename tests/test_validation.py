from __future__ import annotations

import pytest

from elscript.errors import UnknownCharacterError, UnknownPresetError, ValidationError
from elscript.loading import load_document
from elscript.validation import validate_document


def test_unknown_character_has_source_and_yaml_path() -> None:
    loaded = load_document(
        yaml_text="""
elscript: "1.0"
characters:
  MARA: {voice_id: voice}
scenes:
  - id: scene
    script:
      - GHOST: Boo.
"""
    )

    with pytest.raises(UnknownCharacterError) as raised:
        validate_document(loaded)

    assert raised.value.location is not None
    assert raised.value.location.source == "<yaml_text>"
    assert raised.value.location.yaml_path == "$.scenes[0].script[0].GHOST"


def test_unknown_preset_has_actionable_path() -> None:
    loaded = load_document(
        document={
            "elscript": "1.0",
            "characters": {"MARA": {"voice_id": "voice", "preset": "missing"}},
            "scenes": [],
        }
    )

    with pytest.raises(UnknownPresetError) as raised:
        validate_document(loaded)

    assert raised.value.location is not None
    assert raised.value.location.yaml_path == "$.characters.MARA.preset"


def test_explicit_speech_ids_are_globally_unique() -> None:
    loaded = load_document(
        document={
            "elscript": "1.0",
            "characters": {"MARA": {"voice_id": "voice"}},
            "scenes": [
                {
                    "id": "one",
                    "script": [{"MARA": {"id": "shared", "say": "One."}}],
                },
                {
                    "id": "two",
                    "script": [{"MARA": {"id": "shared", "say": "Two."}}],
                },
            ],
        }
    )

    with pytest.raises(ValidationError, match="Duplicate speech entry id") as raised:
        validate_document(loaded)

    assert raised.value.location is not None
    assert raised.value.location.yaml_path == "$.scenes[1].script[0].MARA.id"


def test_api_escape_hatch_preserves_options_but_rejects_credentials() -> None:
    base = {
        "elscript": "1.0",
        "characters": {
            "MARA": {
                "voice_id": "voice",
                "api": {"voice_settings": {"stability": 0.4}},
            }
        },
        "scenes": [],
    }
    validated = validate_document(load_document(document=base))
    assert validated.characters["MARA"].api == {"voice_settings": {"stability": 0.4}}

    base["characters"]["MARA"]["api"]["api_key"] = "must-not-live-in-yaml"  # type: ignore[index]
    with pytest.raises(ValidationError, match="Credentials are not permitted") as raised:
        validate_document(load_document(document=base))
    assert raised.value.location is not None
    assert raised.value.location.yaml_path == "$.characters.MARA.api.api_key"
    assert "must-not-live-in-yaml" not in str(raised.value)
