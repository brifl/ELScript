from __future__ import annotations

from pathlib import Path

import pytest

from elscript import render_document
from elscript.config import resolve_config
from elscript.errors import AuthenticationError, InputError, InvalidYamlError
from elscript.loading import load_document
from elscript.manifest import ManifestWarning, RenderManifest
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


def test_manifest_serialization_recursively_redacts_sensitive_context() -> None:
    manifest = RenderManifest(
        script_id="safe",
        provider="fake",
        models=("fake",),
        output_mode="single",
        output_format="wav_16000",
        duration_seconds=0.0,
        effective_settings={"headers": {"authorization": "Bearer secret"}},
        files=(),
        scenes=(),
        timeline=(),
        segments=(),
        provider_requests=(),
        warnings=(
            ManifestWarning(
                code="W-SECRET",
                message="redacted context",
                severity="warning",
                phase="provider_generation",
                context={"nested": {"provider_api_key": "another-secret"}},
            ),
        ),
    )

    serialized = manifest.to_json()

    assert "Bearer secret" not in serialized
    assert "another-secret" not in serialized
    assert serialized.count("<redacted>") == 2


def test_invalid_yaml_diagnostic_does_not_echo_source_secrets() -> None:
    secret = "yaml-source-secret-value"

    with pytest.raises(InvalidYamlError) as raised:
        load_document(yaml_text=f"elscript: 1.0\nprovider_api_key: {secret}\nbroken: [\n")

    assert raised.value.code == "INVALID_YAML"
    assert raised.value.location is not None
    assert raised.value.location.line == 4
    assert secret not in str(raised.value)


def test_safe_yaml_loader_cannot_instantiate_python_objects(tmp_path: Path) -> None:
    side_effect = tmp_path / "unsafe-object-created"
    yaml_text = (
        "elscript: 1.0\n"
        f"unsafe: !!python/object/apply:os.system ['touch {side_effect}']\n"
        "characters: {}\n"
        "scenes: []\n"
    )

    with pytest.raises(InvalidYamlError):
        load_document(yaml_text=yaml_text)

    assert not side_effect.exists()


def test_recursive_yaml_alias_and_cyclic_mapping_are_rejected() -> None:
    recursive_yaml = "elscript: 1.0\nloop: &loop\n  - *loop\n"

    with pytest.raises(InvalidYamlError, match="Recursive YAML aliases"):
        load_document(yaml_text=recursive_yaml)

    cyclic: dict[str, object] = {"elscript": "1.0"}
    cyclic["loop"] = cyclic
    with pytest.raises(InputError, match="Recursive YAML aliases"):
        load_document(document=cyclic)


def test_malicious_logical_ids_publish_only_contained_sanitized_paths(
    tmp_path: Path,
) -> None:
    speaker = "..\\MARA"
    output = tmp_path / "contained"
    result = render_document(
        {
            "elscript": "1.0",
            "meta": {"id": "../../manifest"},
            "render": {
                "provider": "fake",
                "mode": "speech",
                "output_format": "wav_16000",
            },
            "characters": {speaker: {"voice_id": "../../voice"}},
            "scenes": [
                {
                    "id": "../../scene",
                    "script": [{speaker: {"id": "../../segment", "say": "Contained."}}],
                }
            ],
            "export": {"mode": "segment"},
        },
        output_dir=output,
    )

    published = (*result.files, result.manifest_path)
    assert all(path is not None and path.parent == output.resolve() for path in published)
    assert all(
        ".." not in path.name and "/" not in path.name and "\\" not in path.name
        for path in published
        if path is not None
    )
    assert not (tmp_path / "manifest.manifest.json").exists()
    assert not (tmp_path / "scene_0001_mara.wav").exists()


def test_cache_symlink_cannot_redirect_records_outside_output_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".cache").symlink_to(outside, target_is_directory=True)

    result = render_document(
        {
            "elscript": "1.0",
            "meta": {"id": "cache-boundary"},
            "render": {
                "provider": "fake",
                "mode": "speech",
                "output_format": "wav_16000",
            },
            "characters": {"MARA": {"voice_id": "mara-voice"}},
            "scenes": [{"id": "one", "script": [{"MARA": "Safe."}]}],
        },
        output_dir=tmp_path / "render",
    )

    assert result.cache_hits == 0
    assert result.cache_misses == 1
    assert not tuple(outside.iterdir())
