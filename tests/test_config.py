from __future__ import annotations

from pathlib import Path

import pytest

from elscript.config import discover_env_file, resolve_config
from elscript.domain import RenderOptions
from elscript.errors import InputError
from elscript.loading import load_document
from elscript.validation import validate_document


def _document(overrides: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
    document: dict[str, object] = {
        "elscript": "1.0",
        "characters": {},
        "scenes": [],
    }
    if overrides:
        document.update(overrides)
    return validate_document(load_document(document=document))


def test_leaf_precedence_is_options_yaml_environment_dotenv_defaults(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ELSCRIPT_PROVIDER=dotenv-provider\n"
        "ELSCRIPT_MODEL=dotenv-model\n"
        "ELSCRIPT_OUTPUT_FORMAT=dotenv-format\n",
        encoding="utf-8",
    )
    document = _document(
        {
            "meta": {"language": "fr"},
            "render": {"model": "yaml-model", "output_format": "yaml-format"},
            "export": {"mode": "scene"},
        }
    )

    config = resolve_config(
        document,
        env_file=env_file,
        process_env={"ELSCRIPT_MODEL": "environment-model"},
        options=RenderOptions(
            language="en",
            output_format="explicit-format",
            output_mode="segment",
        ),
    )

    assert config.provider == "dotenv-provider"
    assert config.model == "yaml-model"
    assert config.language == "en"
    assert config.output_format == "explicit-format"
    assert config.output_mode == "segment"


def test_explicit_false_zero_and_empty_values_do_not_fall_through(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ELSCRIPT_ENABLE_LOGGING=true\nELSCRIPT_SEED=91\nELSCRIPT_OUTPUT_FORMAT=from-env\n",
        encoding="utf-8",
    )
    document = _document({"render": {"enable_logging": False}})

    config = resolve_config(
        document,
        env_file=env_file,
        process_env={},
        options={"seed": 0, "output_format": ""},
    )

    assert config.enable_logging is False
    assert config.seed == 0
    assert config.output_format == ""


def test_dotenv_discovery_prefers_source_root_then_cwd(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "story.yaml"
    source.write_text("elscript: '1.0'", encoding="utf-8")
    source_env = project / ".env"
    source_env.write_text("ELSCRIPT_MODEL=source", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    cwd_env = cwd / ".env"
    cwd_env.write_text("ELSCRIPT_MODEL=cwd", encoding="utf-8")

    assert discover_env_file(source=source, cwd=cwd) == source_env.resolve()
    source_env.unlink()
    assert discover_env_file(source=source, cwd=cwd) == cwd_env.resolve()


def test_process_environment_overrides_dotenv_and_path_is_observable(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ELSCRIPT_MODEL=dotenv\n", encoding="utf-8")

    config = resolve_config(
        _document(),
        env_file=env_file,
        process_env={"ELSCRIPT_MODEL": "process"},
    )

    assert config.model == "process"
    assert config.env_file == env_file.resolve()
    assert config.to_public_dict()["env_file"] == str(env_file.resolve())


def test_invalid_environment_values_are_actionable(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="ELSCRIPT_ENABLE_LOGGING must be a boolean"):
        resolve_config(
            _document(),
            cwd=tmp_path,
            process_env={"ELSCRIPT_ENABLE_LOGGING": "sometimes"},
        )

    with pytest.raises(InputError, match="Explicit .env file does not exist"):
        discover_env_file(env_file=tmp_path / "missing.env")


def test_chunking_and_api_are_immutable_leaf_merged() -> None:
    document = _document(
        {
            "render": {
                "chunking": {"max_chars": 900},
                "api": {"settings": {"stability": 0.4, "style": 0.1}},
            }
        }
    )
    config = resolve_config(
        document,
        process_env={},
        options={"api": {"settings": {"style": 0.8}}},
    )

    assert config.chunking.max_chars == 900
    assert config.chunking.preserve_continuity is True
    assert config.api["settings"] == {"stability": 0.4, "style": 0.8}
    with pytest.raises(TypeError):
        config.api["settings"]["style"] = 0.2  # type: ignore[index]
