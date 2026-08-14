from __future__ import annotations

import pytest

from elscript.errors import ValidationError
from elscript.loading import load_document
from elscript.validation import validate_document


def _validate(document: dict[str, object]) -> None:
    validate_document(load_document(document=document))


def test_scalar_and_structured_script_forms_validate() -> None:
    _validate(
        {
            "elscript": "1.0",
            "presets": {"base": {"emotion": "calm", "intensity": 0.2}},
            "characters": {"MARA": {"voice_id": "voice", "preset": "base"}},
            "scenes": [
                {
                    "id": "scene",
                    "script": [
                        {"MARA": "Hello."},
                        {
                            "MARA": {
                                "set": {"emotion": "frightened", "intensity": 0.8},
                                "with": {"volume": "quiet"},
                                "cue": ["inhales"],
                                "tags": ["nervous"],
                                "say": [
                                    {"text": "Wait."},
                                    {"set": {"pace": "slow"}},
                                    {"cue": "long pause"},
                                    {"with": {"volume": "whisper"}, "text": "Listen."},
                                    {"reset": ["pace"]},
                                ],
                            }
                        },
                        {"pause": 0.5},
                        {"marker": "reveal"},
                        {"note": "Not spoken."},
                    ],
                }
            ],
        }
    )


@pytest.mark.parametrize("value", ["on", "off"])
def test_unquoted_text_normalization_uses_yaml_1_2_string_semantics(value: str) -> None:
    loaded = load_document(
        yaml_text=f"""
elscript: "1.0"
render:
  text_normalization: {value}
characters: {{}}
scenes: []
"""
    )

    validated = validate_document(loaded)

    assert validated.render.text_normalization == value


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        ({"unknown": True}, "$.unknown"),
        ({"elscript": "2.0"}, "$.elscript"),
        (
            {"characters": {"MARA": {"voice_id": "voice", "defaults": {"intensity": 1.1}}}},
            "$.characters.MARA.defaults.intensity",
        ),
    ],
)
def test_unknown_version_and_out_of_range_values_fail(
    mutation: dict[str, object], expected_path: str
) -> None:
    document: dict[str, object] = {
        "elscript": "1.0",
        "characters": {"MARA": {"voice_id": "voice"}},
        "scenes": [{"id": "scene", "script": [{"MARA": "Hello."}]}],
    }
    document.update(mutation)

    with pytest.raises(ValidationError) as raised:
        _validate(document)

    assert raised.value.location is not None
    assert raised.value.location.yaml_path == expected_path


def test_missing_voice_and_malformed_reset_fail() -> None:
    with pytest.raises(ValidationError) as missing_voice:
        _validate(
            {
                "elscript": "1.0",
                "characters": {"MARA": {}},
                "scenes": [{"id": "scene", "script": []}],
            }
        )
    assert missing_voice.value.location is not None
    assert missing_voice.value.location.yaml_path == "$.characters.MARA.voice_id"

    with pytest.raises(ValidationError, match="reset"):
        _validate(
            {
                "elscript": "1.0",
                "characters": {"MARA": {"voice_id": "voice"}},
                "scenes": [
                    {"id": "scene", "script": [{"MARA": {"reset": "not-a-state", "say": "Hi"}}]}
                ],
            }
        )
