"""Layered render configuration with explicit secret handling."""

from __future__ import annotations

import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from dotenv import dotenv_values

from .domain import OutputMode, RenderOptions
from .errors import InputError
from .redaction import SecretValue, is_sensitive_key, redact
from .schema import ELScriptDocument

_DEFAULTS: dict[str, Any] = {
    "provider": "elevenlabs",
    "render_mode": "auto",
    "model": "eleven_v3",
    "output_format": "mp3_44100_128",
    "output_mode": "single",
    "timestamps": False,
    "seed": None,
    "text_normalization": "auto",
    "language_text_normalization": False,
    "enable_logging": True,
    "normalize_loudness": False,
    "manifest_enabled": True,
    "include_source_text": True,
    "language": None,
    "chunking": {
        "max_chars": 1800,
        "prefer_scene_boundaries": True,
        "prefer_utterance_boundaries": True,
        "preserve_continuity": True,
    },
    "api": {},
}

_ENVIRONMENT_KEYS = {
    "ELSCRIPT_PROVIDER": "provider",
    "ELSCRIPT_RENDER_MODE": "render_mode",
    "ELSCRIPT_MODEL": "model",
    "ELSCRIPT_LANGUAGE": "language",
    "ELSCRIPT_OUTPUT_FORMAT": "output_format",
    "ELSCRIPT_OUTPUT_MODE": "output_mode",
    "ELSCRIPT_TIMESTAMPS": "timestamps",
    "ELSCRIPT_SEED": "seed",
    "ELSCRIPT_TEXT_NORMALIZATION": "text_normalization",
    "ELSCRIPT_LANGUAGE_TEXT_NORMALIZATION": "language_text_normalization",
    "ELSCRIPT_ENABLE_LOGGING": "enable_logging",
    "ELSCRIPT_NORMALIZE_LOUDNESS": "normalize_loudness",
}
_BOOLEAN_KEYS = {
    "timestamps",
    "language_text_normalization",
    "enable_logging",
    "normalize_loudness",
}
_INTEGER_KEYS = {"seed"}
_OPTION_KEYS = frozenset(_DEFAULTS)
_STRING_OPTION_KEYS = {
    "language",
    "model",
    "output_format",
    "output_mode",
    "provider",
    "render_mode",
    "text_normalization",
}
_BOOLEAN_OPTION_KEYS = _BOOLEAN_KEYS | {
    "include_source_text",
    "manifest_enabled",
}
_CHUNKING_KEYS = {
    "max_chars",
    "prefer_scene_boundaries",
    "prefer_utterance_boundaries",
    "preserve_continuity",
}


class _ClearValue(Enum):
    CLEAR = "clear"


def _deep_overlay(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for key, value in incoming.items():
        if value is None:
            continue
        if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
            child = dict(target[key])
            _deep_overlay(child, value)
            target[key] = child
        else:
            target[key] = deepcopy(value)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _parse_boolean(name: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise InputError(f"{name} must be a boolean value, got {value!r}")


def _environment_layer(environment: Mapping[str, str]) -> dict[str, Any]:
    layer: dict[str, Any] = {}
    for environment_key, config_key in _ENVIRONMENT_KEYS.items():
        if environment_key not in environment:
            continue
        value: Any = environment[environment_key]
        if config_key in _BOOLEAN_KEYS:
            value = _parse_boolean(environment_key, value)
        elif config_key in _INTEGER_KEYS:
            if value == "":
                value = _ClearValue.CLEAR
            else:
                try:
                    value = int(value)
                except ValueError as error:
                    raise InputError(
                        f"{environment_key} must be an integer, got {value!r}"
                    ) from error
        layer[config_key] = value
    return layer


def discover_env_file(
    *,
    source: str | Path | None = None,
    env_file: str | Path | None = None,
    cwd: str | Path | None = None,
) -> Path | None:
    """Resolve explicit, source-root, then working-directory dotenv discovery."""

    if env_file is not None:
        explicit = Path(env_file).resolve()
        if not explicit.is_file():
            raise InputError(f"Explicit .env file does not exist or is not a file: {explicit}")
        return explicit

    working_directory = Path.cwd() if cwd is None else Path(cwd)
    candidates: list[tuple[Path, Path]] = []
    if source is not None:
        source_path = Path(source)
        source_root = source_path if source_path.is_dir() else source_path.parent
        candidates.append((source_root / ".env", source_root.resolve()))
    candidates.append((working_directory / ".env", working_directory.resolve()))

    seen: set[Path] = set()
    for candidate, allowed_root in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            if not resolved.is_relative_to(allowed_root):
                raise InputError(
                    f"Automatically discovered .env resolves outside its root: {candidate}"
                )
            return resolved
    return None


def _dotenv_layer(env_path: Path | None) -> dict[str, str]:
    if env_path is None:
        return {}
    try:
        parsed = dotenv_values(env_path, encoding="utf-8", interpolate=False)
    except OSError as error:
        raise InputError(f"Unable to read .env file at {env_path}: {error}") from error
    return {key: value for key, value in parsed.items() if value is not None}


def _yaml_layer(document: ELScriptDocument) -> dict[str, Any]:
    render = document.render.model_dump(exclude_unset=True, by_alias=True)
    export = document.export.model_dump(exclude_unset=True, by_alias=True)
    layer: dict[str, Any] = {}
    for key, value in render.items():
        layer["render_mode" if key == "mode" else key] = value
    if "mode" in export:
        layer["output_mode"] = export["mode"]
    if "normalize_loudness" in export:
        layer["normalize_loudness"] = export["normalize_loudness"]
    manifest = export.get("manifest", {})
    if "enabled" in manifest:
        layer["manifest_enabled"] = manifest["enabled"]
    if "include_source_text" in manifest:
        layer["include_source_text"] = manifest["include_source_text"]
    if document.meta.language is not None:
        layer["language"] = document.meta.language
    return layer


def _options_layer(options: RenderOptions | Mapping[str, Any] | None) -> dict[str, Any]:
    if options is None:
        return {}
    if isinstance(options, RenderOptions):
        raw = {field.name: getattr(options, field.name) for field in fields(options)}
    else:
        raw = dict(options)
    unknown = set(raw) - _OPTION_KEYS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise InputError(f"Unknown explicit render option(s): {names}")
    result = {key: value for key, value in raw.items() if value is not None}
    _reject_credentials(result.get("api"), path="api")
    output_mode = result.get("output_mode")
    if isinstance(output_mode, OutputMode):
        result["output_mode"] = output_mode.value
    _validate_explicit_options(result)
    return result


def _reject_credentials(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if is_sensitive_key(key):
                raise InputError(
                    f"Credentials must use the explicit credential input, not {child_path}"
                )
            _reject_credentials(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials(child, path=f"{path}[{index}]")


def _validate_explicit_options(options: Mapping[str, Any]) -> None:
    for key in _STRING_OPTION_KEYS:
        value = options.get(key)
        if value is not None and not isinstance(value, str):
            raise InputError(f"Explicit option {key} must be a string")
    for key in _BOOLEAN_OPTION_KEYS:
        value = options.get(key)
        if value is not None and not isinstance(value, bool):
            raise InputError(f"Explicit option {key} must be a boolean")
    seed = options.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise InputError("Explicit option seed must be an integer")
    api = options.get("api")
    if api is not None and not isinstance(api, Mapping):
        raise InputError("Explicit option api must be a mapping")
    chunking = options.get("chunking")
    if chunking is None:
        return
    if not isinstance(chunking, Mapping):
        raise InputError("Explicit option chunking must be a mapping")
    unknown = set(chunking) - _CHUNKING_KEYS
    if unknown:
        raise InputError(f"Unknown explicit chunking option(s): {', '.join(sorted(unknown))}")
    max_chars = chunking.get("max_chars")
    if max_chars is not None and (
        isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1
    ):
        raise InputError("Explicit chunking option max_chars must be a positive integer")
    for key in _CHUNKING_KEYS - {"max_chars"}:
        value = chunking.get(key)
        if value is not None and not isinstance(value, bool):
            raise InputError(f"Explicit chunking option {key} must be a boolean")


@dataclass(frozen=True, slots=True)
class EffectiveChunking:
    max_chars: int
    prefer_scene_boundaries: bool
    prefer_utterance_boundaries: bool
    preserve_continuity: bool


@dataclass(frozen=True, slots=True)
class EffectiveConfig:
    provider: str
    render_mode: str
    model: str
    output_format: str
    output_mode: str
    timestamps: bool
    seed: int | None
    text_normalization: str
    language_text_normalization: bool
    enable_logging: bool
    normalize_loudness: bool
    manifest_enabled: bool
    include_source_text: bool
    language: str | None
    chunking: EffectiveChunking
    api: Mapping[str, Any]
    env_file: Path | None
    credential: SecretValue | None = field(default=None, repr=False, compare=False)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize effective non-secret settings for diagnostics and manifests."""

        return {
            "provider": self.provider,
            "render_mode": self.render_mode,
            "model": self.model,
            "output_format": self.output_format,
            "output_mode": self.output_mode,
            "timestamps": self.timestamps,
            "seed": self.seed,
            "text_normalization": self.text_normalization,
            "language_text_normalization": self.language_text_normalization,
            "enable_logging": self.enable_logging,
            "normalize_loudness": self.normalize_loudness,
            "manifest_enabled": self.manifest_enabled,
            "include_source_text": self.include_source_text,
            "language": self.language,
            "chunking": asdict(self.chunking),
            "api": redact(dict(self.api)),
            "env_file": str(self.env_file) if self.env_file is not None else None,
        }

    def fingerprint_inputs(self) -> dict[str, Any]:
        """Return render-material configuration without credentials or output location."""

        values = self.to_public_dict()
        values.pop("env_file", None)
        values.pop("output_mode", None)
        values.pop("manifest_enabled", None)
        values.pop("include_source_text", None)
        return values


def resolve_config(
    document: ELScriptDocument,
    *,
    options: RenderOptions | Mapping[str, Any] | None = None,
    source: str | Path | None = None,
    env_file: str | Path | None = None,
    cwd: str | Path | None = None,
    process_env: Mapping[str, str] | None = None,
    credential: str | None = None,
) -> EffectiveConfig:
    """Resolve defaults < dotenv < environment < YAML < explicit options."""

    selected_env_file = discover_env_file(source=source, env_file=env_file, cwd=cwd)
    dotenv = _dotenv_layer(selected_env_file)
    environment = os.environ if process_env is None else process_env

    values = deepcopy(_DEFAULTS)
    _deep_overlay(values, _environment_layer(dotenv))
    _deep_overlay(values, _environment_layer(environment))
    _deep_overlay(values, _yaml_layer(document))
    _deep_overlay(values, _options_layer(options))
    if values["seed"] is _ClearValue.CLEAR:
        values["seed"] = None

    chunking = values["chunking"]
    effective_chunking = EffectiveChunking(**chunking)
    secret_source = (
        credential
        if credential is not None
        else environment.get("ELEVENLABS_API_KEY", dotenv.get("ELEVENLABS_API_KEY"))
    )
    return EffectiveConfig(
        provider=values["provider"],
        render_mode=values["render_mode"],
        model=values["model"],
        output_format=values["output_format"],
        output_mode=values["output_mode"],
        timestamps=values["timestamps"],
        seed=values["seed"],
        text_normalization=values["text_normalization"],
        language_text_normalization=values["language_text_normalization"],
        enable_logging=values["enable_logging"],
        normalize_loudness=values["normalize_loudness"],
        manifest_enabled=values["manifest_enabled"],
        include_source_text=values["include_source_text"],
        language=values["language"],
        chunking=effective_chunking,
        api=_freeze(values["api"]),
        env_file=selected_env_file,
        credential=SecretValue(secret_source) if secret_source is not None else None,
    )
