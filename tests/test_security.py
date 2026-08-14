from __future__ import annotations

from pathlib import Path

import pytest

from elscript.config import resolve_config
from elscript.errors import AuthenticationError, InputError
from elscript.loading import load_document
from elscript.output import sanitize_filename_component
from elscript.validation import validate_document


def _document():  # type: ignore[no-untyped-def]
    return validate_document(
        load_document(document={"elscript": "1.0", "characters": {}, "scenes": []})
    )


def test_credential_precedence_and_every_public_representation_are_secret_free(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ELEVENLABS_API_KEY=dotenv-secret\n", encoding="utf-8")
    config = resolve_config(
        _document(),
        env_file=env_file,
        process_env={"ELEVENLABS_API_KEY": "process-secret"},
        credential="explicit-secret",
    )

    assert config.credential is not None
    assert config.credential.reveal() == "explicit-secret"
    representations = (repr(config), str(config), repr(config.credential), config.to_public_dict())
    assert all("explicit-secret" not in repr(value) for value in representations)
    assert "credential" not in config.to_public_dict()
    assert "credential" not in config.fingerprint_inputs()


def test_empty_process_credential_masks_dotenv_without_leaking(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ELEVENLABS_API_KEY=dotenv-secret\n", encoding="utf-8")
    config = resolve_config(
        _document(),
        env_file=env_file,
        process_env={"ELEVENLABS_API_KEY": ""},
    )

    assert config.credential is not None
    assert config.credential.reveal() == ""
    assert "dotenv-secret" not in repr(config)


def test_shared_error_redaction_hides_nested_credential_variants() -> None:
    error = AuthenticationError(
        "rejected",
        context={
            "headers": {"authorization_header": "Bearer secret"},
            "provider_api_key": "secret",
            "status": 401,
        },
    )

    assert "Bearer secret" not in str(error)
    assert "secret" not in str(error)
    assert error.context["status"] == 401


def test_explicit_provider_options_cannot_smuggle_credentials() -> None:
    with pytest.raises(InputError, match="explicit credential input") as raised:
        resolve_config(
            _document(),
            process_env={},
            options={"api": {"transport": {"provider_api_key": "do-not-leak"}}},
        )

    assert "do-not-leak" not in str(raised.value)


def test_output_path_components_cannot_retain_traversal_or_platform_names(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    components = ["../../outside", "..\\outside", "/absolute", "CON", "...", "a:b"]

    for component in components:
        safe = sanitize_filename_component(component)
        candidate = (root / f"{safe}.wav").resolve(strict=False)
        assert candidate.parent == root
        assert "/" not in safe and "\\" not in safe
        assert safe not in {"", ".", "..", "CON"}
