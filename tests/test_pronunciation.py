from __future__ import annotations

import pytest

from elscript.compiler import compile_document
from elscript.config import resolve_config
from elscript.errors import UnsupportedModelFeatureError
from elscript.loading import load_document
from elscript.providers.elevenlabs_prompt import prepare_elevenlabs
from elscript.validation import validate_document


def _prompt(
    text: str,
    terms: dict[str, dict[str, str]],
    *,
    model: str = "eleven_v3",
):  # type: ignore[no-untyped-def]
    document = validate_document(
        load_document(
            document={
                "elscript": "1.0",
                "pronunciation": {"terms": terms},
                "characters": {"MARA": {"voice_id": "mara", "model": model}},
                "scenes": [{"id": "scene", "script": [{"MARA": text}]}],
            }
        )
    )
    config = resolve_config(document, process_env={})
    compiled = compile_document(document, config)
    translation = prepare_elevenlabs(compiled, document.pronunciation)
    return (
        translation.prepared_segments[compiled.segments[0].id].provider_text,
        translation.warnings,
    )


def test_term_matching_is_exact_case_sensitive_and_boundary_safe() -> None:
    prompt, _ = _prompt(
        "Calypso calypso Calypsoid (Calypso); XJ-9X XJ-9.",
        {
            "Calypso": {"ipa": "kəˈlɪpsoʊ"},
            "XJ-9": {"say_as": "X J Nine"},
        },
    )

    assert prompt == (
        "/kəˈlɪpsoʊ/ calypso Calypsoid (/kəˈlɪpsoʊ/); XJ-9X X J Nine."
    )


def test_longest_overlapping_term_wins_without_recursive_replacement() -> None:
    prompt, _ = _prompt(
        "New York and New",
        {
            "New": {"say_as": "Old"},
            "New York": {"say_as": "NYC"},
            "Old": {"say_as": "Ancient"},
        },
    )

    assert prompt == "NYC and Old"


def test_v3_accepts_bare_or_wrapped_ipa_without_double_slashes() -> None:
    bare, _ = _prompt("Term", {"Term": {"ipa": "tɜːm"}})
    wrapped, _ = _prompt("Term", {"Term": {"ipa": "/tɜːm/"}})

    assert bare == "/tɜːm/"
    assert wrapped == bare


def test_non_v3_uses_explicit_alias_with_a_stable_warning() -> None:
    prompt, warnings = _prompt(
        "Calypso",
        {"Calypso": {"ipa": "kəˈlɪpsoʊ", "say_as": "Kuh-LIP-so"}},
        model="eleven_multilingual_v2",
    )

    assert prompt == "Kuh-LIP-so"
    assert [warning.code for warning in warnings] == ["ELEVENLABS_IPA_ALIAS_FALLBACK"]


def test_non_v3_ipa_without_alias_fails_instead_of_losing_intent() -> None:
    with pytest.raises(UnsupportedModelFeatureError, match="cannot honor IPA"):
        _prompt(
            "Calypso",
            {"Calypso": {"ipa": "kəˈlɪpsoʊ"}},
            model="eleven_multilingual_v2",
        )


def test_unused_ipa_term_does_not_block_or_warn_for_another_model() -> None:
    prompt, warnings = _prompt(
        "Nothing to replace.",
        {"Calypso": {"ipa": "kəˈlɪpsoʊ"}},
        model="eleven_multilingual_v2",
    )

    assert prompt == "Nothing to replace."
    assert warnings == ()
