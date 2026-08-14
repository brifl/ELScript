from __future__ import annotations

from elscript.compiler import compile_document
from elscript.config import resolve_config
from elscript.domain import MarkerEvent, NoteEvent, PauseEvent, SpeechSegment
from elscript.loading import load_document
from elscript.validation import validate_document


def _compile(document: dict[str, object]):  # type: ignore[no-untyped-def]
    validated = validate_document(load_document(document=document))
    return compile_document(validated, resolve_config(validated, process_env={}))


def _base(scenes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "elscript": "1.0",
        "presets": {"calm": {"emotion": "calm", "intensity": 0.2}},
        "characters": {
            "MARA": {"voice_id": "mara", "preset": "calm"},
            "ORION": {"voice_id": "orion"},
        },
        "scenes": scenes,
    }


def test_persistent_state_is_per_character_and_reset_uses_baseline() -> None:
    compiled = _compile(
        _base(
            [
                {
                    "id": "scene",
                    "script": [
                        {
                            "MARA": {
                                "set": {"emotion": "frightened", "intensity": 0.8},
                                "say": "One",
                            }
                        },
                        {"ORION": "Reply"},
                        {"MARA": {"set": {"intensity": 0.9}, "say": "Two"}},
                        {"MARA": {"reset": "intensity", "say": "Three"}},
                        {"MARA": {"reset": "all", "say": "Four"}},
                    ],
                }
            ]
        )
    )

    mara = [segment for segment in compiled.segments if segment.speaker == "MARA"]
    assert (mara[0].performance.emotion, mara[0].performance.intensity) == ("frightened", 0.8)
    assert (mara[1].performance.emotion, mara[1].performance.intensity) == ("frightened", 0.9)
    assert (mara[2].performance.emotion, mara[2].performance.intensity) == ("frightened", 0.2)
    assert (mara[3].performance.emotion, mara[3].performance.intensity) == ("calm", 0.2)
    assert compiled.segments[1].performance.emotion == "neutral"


def test_temporary_state_never_mutates_persistent_state() -> None:
    compiled = _compile(
        _base(
            [
                {
                    "id": "scene",
                    "script": [
                        {"MARA": {"with": {"volume": "whisper"}, "say": "Temporary"}},
                        {"MARA": "Normal"},
                        {
                            "MARA": {
                                "with": {"pace": "slow"},
                                "say": [
                                    {"text": "Parent"},
                                    {"with": {"volume": "quiet"}, "text": "Nested"},
                                ],
                            }
                        },
                        {"MARA": "After"},
                    ],
                }
            ]
        )
    )

    assert [segment.performance.volume for segment in compiled.segments] == [
        "whisper",
        "normal",
        "normal",
        "quiet",
        "normal",
    ]
    assert [segment.performance.pace for segment in compiled.segments] == [
        "normal",
        "normal",
        "slow",
        "slow",
        "normal",
    ]


def test_scene_state_carries_only_when_explicitly_inherited() -> None:
    compiled = _compile(
        _base(
            [
                {
                    "id": "one",
                    "script": [{"MARA": {"set": {"emotion": "angry"}, "say": "One"}}],
                },
                {"id": "two", "inherit_character_state": True, "script": [{"MARA": "Two"}]},
                {"id": "three", "script": [{"MARA": "Three"}]},
            ]
        )
    )

    assert [segment.performance.emotion for segment in compiled.segments] == [
        "angry",
        "angry",
        "calm",
    ]
    assert compiled.scenes[1].initial_character_states["MARA"].emotion == "angry"
    assert compiled.scenes[2].initial_character_states["MARA"].emotion == "calm"


def test_structured_say_preserves_state_only_and_cue_only_items() -> None:
    compiled = _compile(
        _base(
            [
                {
                    "id": "scene",
                    "script": [
                        {
                            "MARA": {
                                "cue": "inhales",
                                "tags": ["nervous"],
                                "say": [
                                    {"text": "Before"},
                                    {"set": {"emotion": "relieved"}},
                                    {"cue": "laughs"},
                                    {"with": {"volume": "whisper"}, "text": "After"},
                                ],
                            }
                        }
                    ],
                }
            ]
        )
    )

    assert [segment.text for segment in compiled.segments] == ["Before", None, "After"]
    assert compiled.segments[0].cues == ("inhales",)
    assert compiled.segments[0].tags == ("nervous",)
    assert compiled.segments[1].cues == ("laughs",)
    assert compiled.segments[1].performance.emotion == "relieved"
    assert compiled.segments[2].performance.volume == "whisper"
    assert compiled.final_character_states["MARA"].volume == "normal"


def test_non_speech_events_keep_order_without_consuming_ordinals() -> None:
    compiled = _compile(
        _base(
            [
                {
                    "id": "scene",
                    "script": [
                        {"MARA": "One"},
                        {"pause": 1.25},
                        {"marker": "reveal"},
                        {"note": "not spoken"},
                        {"ORION": "Two"},
                    ],
                }
            ]
        )
    )

    assert [type(event) for event in compiled.timeline] == [
        SpeechSegment,
        PauseEvent,
        MarkerEvent,
        NoteEvent,
        SpeechSegment,
    ]
    assert [segment.ordinal for segment in compiled.segments] == [1, 2]
    assert compiled.timeline[1].after_ordinal == 1  # type: ignore[union-attr]
    assert compiled.timeline[2].after_ordinal == 1  # type: ignore[union-attr]


def test_ids_are_deterministic_and_single_explicit_id_is_unchanged() -> None:
    document = _base(
        [
            {
                "id": "scene",
                "script": [
                    {"MARA": {"id": "authored.id", "say": "One"}},
                    {"ORION": "Two"},
                ],
            }
        ]
    )

    first = _compile(document)
    second = _compile(document)

    assert [segment.id for segment in first.segments] == [
        "authored.id",
        "scene.orion.0002",
    ]
    assert [segment.id for segment in first.segments] == [segment.id for segment in second.segments]


def test_structured_explicit_id_is_preserved_as_segment_prefix() -> None:
    compiled = _compile(
        _base(
            [
                {
                    "id": "scene",
                    "script": [
                        {
                            "MARA": {
                                "id": "authored.turn",
                                "say": [
                                    {"text": "One"},
                                    {"cue": "laughs"},
                                    {"text": "Two"},
                                ],
                            }
                        }
                    ],
                }
            ]
        )
    )

    assert [segment.id for segment in compiled.segments] == [
        "authored.turn",
        "authored.turn.02",
        "authored.turn.03",
    ]
    assert {segment.entry_id for segment in compiled.segments} == {"authored.turn"}


def test_provider_state_is_leaf_merged_and_immutable() -> None:
    document = _base(
        [
            {
                "id": "scene",
                "render": {"model": "scene-model", "seed": 7},
                "api": {"settings": {"style": 0.8}},
                "script": [
                    {
                        "MARA": {
                            "api": {"settings": {"speed": 0.9}},
                            "say": [{"api": {"settings": {"style": 0.5}}, "text": "One"}],
                        }
                    }
                ],
            }
        ]
    )
    document["presets"]["calm"]["api"] = {"settings": {"stability": 0.4}}  # type: ignore[index]
    document["characters"]["MARA"]["api"] = {"settings": {"speed": 1.0}}  # type: ignore[index]

    compiled = _compile(document)
    segment = compiled.segments[0]

    assert segment.model == "scene-model"
    assert segment.render_settings["seed"] == 7
    assert segment.provider_options["settings"] == {
        "stability": 0.4,
        "speed": 0.9,
        "style": 0.5,
    }
