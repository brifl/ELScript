"""Source-aware schema and cross-reference validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .domain import LoadedDocument, PipelinePhase, SourceLocation
from .errors import UnknownCharacterError, UnknownPresetError, ValidationError
from .schema import ELScriptDocument

_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)
_EVENT_KEYS = frozenset({"pause", "note", "marker"})


def _is_sensitive_key(key: str) -> bool:
    return (
        key in _SENSITIVE_KEYS
        or key.startswith("authorization_")
        or key.endswith(("_api_key", "_password", "_secret", "_token"))
    )


def _yaml_path(parts: Sequence[object]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


def _nearest_location(document: LoadedDocument, path: str) -> SourceLocation:
    candidate = path
    while candidate != "$":
        if candidate in document.provenance:
            location = document.provenance[candidate]
            return SourceLocation(
                source=location.source,
                yaml_path=path,
                line=location.line,
                column=location.column,
            )
        if candidate.endswith("]"):
            candidate = candidate[: candidate.rfind("[")]
        else:
            candidate = candidate.rsplit(".", 1)[0]
    root = document.provenance.get("$", SourceLocation(source="<unknown>"))
    return SourceLocation(source=root.source, yaml_path=path, line=root.line, column=root.column)


def _reject_credentials_in_api(
    value: object,
    *,
    document: LoadedDocument,
    path: str = "$",
    inside_api: bool = False,
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            key_text = str(key).casefold().replace("-", "_")
            child_inside_api = inside_api or key == "api"
            if child_inside_api and _is_sensitive_key(key_text):
                raise ValidationError(
                    "Credentials are not permitted in ELScript api mappings",
                    location=_nearest_location(document, child_path),
                    context={"path": child_path},
                )
            _reject_credentials_in_api(
                child,
                document=document,
                path=child_path,
                inside_api=child_inside_api,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_credentials_in_api(
                child,
                document=document,
                path=f"{path}[{index}]",
                inside_api=inside_api,
            )


def _raise_schema_error(document: LoadedDocument, error: PydanticValidationError) -> None:
    detail = error.errors(include_url=False)[0]
    path = _yaml_path(detail["loc"])
    message = str(detail["msg"])
    raise ValidationError(
        message,
        location=_nearest_location(document, path),
        context={"path": path, "error_type": detail["type"]},
    ) from error


def _entry_parts(entry: Mapping[str, Any]) -> tuple[str, object]:
    return next(iter(entry.items()))


def _validate_references(document: LoadedDocument, schema: ELScriptDocument) -> None:
    explicit_ids: dict[str, SourceLocation] = {}

    for character_id, character in schema.characters.items():
        if character_id in _EVENT_KEYS:
            path = f"$.characters.{character_id}"
            raise ValidationError(
                f"Character id {character_id!r} is reserved for a timeline event",
                phase=PipelinePhase.REFERENCE_VALIDATION,
                location=_nearest_location(document, path),
                context={"path": path, "character_id": character_id},
            )
        if character.preset is not None and character.preset not in schema.presets:
            path = f"$.characters.{character_id}.preset"
            raise UnknownPresetError(
                f"Character {character_id!r} references unknown preset {character.preset!r}",
                phase=PipelinePhase.REFERENCE_VALIDATION,
                location=_nearest_location(document, path),
                context={"path": path, "preset": character.preset},
            )

    for scene_index, scene in enumerate(schema.scenes):
        for entry_index, script_entry in enumerate(scene.script):
            speaker, payload = _entry_parts(script_entry.root)
            if speaker in _EVENT_KEYS:
                continue
            entry_path = f"$.scenes[{scene_index}].script[{entry_index}]"
            if speaker not in schema.characters:
                path = f"{entry_path}.{speaker}"
                raise UnknownCharacterError(
                    f"Scene {scene.id!r} references unknown character {speaker!r}",
                    phase=PipelinePhase.REFERENCE_VALIDATION,
                    location=_nearest_location(document, path),
                    context={"path": path, "scene_id": scene.id, "character_id": speaker},
                )
            if not isinstance(payload, Mapping):
                continue
            explicit_id = payload.get("id")
            if not isinstance(explicit_id, str):
                continue
            path = f"{entry_path}.{speaker}.id"
            location = _nearest_location(document, path)
            if explicit_id in explicit_ids:
                first = explicit_ids[explicit_id]
                raise ValidationError(
                    f"Duplicate speech entry id {explicit_id!r}",
                    phase=PipelinePhase.REFERENCE_VALIDATION,
                    location=location,
                    context={
                        "path": path,
                        "first_source": first.source,
                        "second_source": location.source,
                    },
                )
            explicit_ids[explicit_id] = location


def validate_document(document: LoadedDocument) -> ELScriptDocument:
    """Validate structure, credentials, and cross references before compilation."""

    _reject_credentials_in_api(document.data, document=document)
    try:
        validated = ELScriptDocument.model_validate(document.data)
    except PydanticValidationError as error:
        _raise_schema_error(document, error)
    _validate_references(document, validated)
    return validated
