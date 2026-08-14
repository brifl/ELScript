"""Section-aware deterministic merge semantics for ELScript fragments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from .domain import LoadedDocument, SourceLocation
from .errors import MergeConflictError, MergeError


def _child_path(parent: str, key: object) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    return f"{parent}.{key}"


def _location(document: LoadedDocument, path: str) -> SourceLocation:
    if path in document.provenance:
        return document.provenance[path]
    source = str(document.sources[0]) if document.sources else "<unknown>"
    return SourceLocation(source=source, yaml_path=path)


def _copy_provenance_branch(
    target: dict[str, SourceLocation],
    source: Mapping[str, SourceLocation],
    path: str,
) -> None:
    for candidate, location in source.items():
        belongs_to_branch = (
            candidate == path
            or candidate.startswith(f"{path}.")
            or candidate.startswith(f"{path}[")
        )
        if belongs_to_branch:
            target[candidate] = location


def _raise_conflict(
    path: str,
    first: object,
    second: object,
    *,
    target_provenance: Mapping[str, SourceLocation],
    incoming: LoadedDocument,
) -> None:
    first_location = target_provenance.get(path, SourceLocation(source="<unknown>", yaml_path=path))
    second_location = _location(incoming, path)
    message = (
        f"Conflicting definitions for {path} in "
        f"{first_location.source} and {second_location.source}"
    )
    raise MergeConflictError(
        message,
        location=second_location,
        context={
            "path": path,
            "first_source": first_location.source,
            "second_source": second_location.source,
            "first_value": first,
            "second_value": second,
        },
    )


def _stable_union(first: list[Any], second: list[Any]) -> list[Any]:
    result = deepcopy(first)
    for item in second:
        if item not in result:
            result.append(deepcopy(item))
    return result


def _merge_dictionary_references(
    first: list[Any],
    second: list[Any],
    *,
    path: str,
    target_provenance: Mapping[str, SourceLocation],
    incoming: LoadedDocument,
) -> list[Any]:
    result = deepcopy(first)
    by_id = {
        item.get("id"): item
        for item in result
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    for item in second:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            existing = by_id.get(item["id"])
            if existing is not None and existing != item:
                _raise_conflict(
                    path,
                    existing,
                    item,
                    target_provenance=target_provenance,
                    incoming=incoming,
                )
            if existing is not None:
                continue
            by_id[item["id"]] = item
        elif item in result:
            continue
        result.append(deepcopy(item))
    return result


def _merge_values(
    target: dict[Any, Any],
    incoming_mapping: Mapping[Any, Any],
    *,
    path: str,
    target_provenance: dict[str, SourceLocation],
    incoming: LoadedDocument,
) -> None:
    for key, incoming_value in incoming_mapping.items():
        child_path = _child_path(path, key)
        if key not in target:
            target[key] = deepcopy(incoming_value)
            _copy_provenance_branch(target_provenance, incoming.provenance, child_path)
            continue

        target_value = target[key]
        if isinstance(target_value, Mapping) and isinstance(incoming_value, Mapping):
            mutable_target = dict(target_value)
            _merge_values(
                mutable_target,
                incoming_value,
                path=child_path,
                target_provenance=target_provenance,
                incoming=incoming,
            )
            target[key] = mutable_target
            continue
        if isinstance(target_value, list) and isinstance(incoming_value, list):
            if child_path == "$.meta.tags":
                target[key] = _stable_union(target_value, incoming_value)
                continue
            if child_path == "$.pronunciation.dictionaries":
                target[key] = _merge_dictionary_references(
                    target_value,
                    incoming_value,
                    path=child_path,
                    target_provenance=target_provenance,
                    incoming=incoming,
                )
                continue
        if target_value != incoming_value:
            _raise_conflict(
                child_path,
                target_value,
                incoming_value,
                target_provenance=target_provenance,
                incoming=incoming,
            )


def _scene_sort_key(scene_record: tuple[dict[str, Any], SourceLocation, int]) -> tuple[Any, ...]:
    scene, location, position = scene_record
    order = scene.get("order")
    if isinstance(order, (int, float)) and not isinstance(order, bool):
        return (0, order, location.source, position)
    return (1, 0, location.source, position)


def _append_scene_provenance(
    target: dict[str, SourceLocation],
    incoming: LoadedDocument,
    *,
    old_index: int,
    new_index: int,
) -> None:
    old_prefix = f"$.scenes[{old_index}]"
    new_prefix = f"$.scenes[{new_index}]"
    for path, location in incoming.provenance.items():
        if path == old_prefix or path.startswith(f"{old_prefix}.") or path.startswith(
            f"{old_prefix}["
        ):
            target[f"{new_prefix}{path[len(old_prefix):]}"] = SourceLocation(
                source=location.source,
                yaml_path=f"{new_prefix}{path[len(old_prefix):]}",
                line=location.line,
                column=location.column,
            )


def merge_documents(documents: Sequence[LoadedDocument]) -> LoadedDocument:
    """Merge parsed fragments without allowing traversal order to resolve conflicts."""

    if not documents:
        raise MergeError("At least one parsed document is required for merge")

    merged: dict[Any, Any] = {}
    provenance: dict[str, SourceLocation] = {}
    scene_records: list[tuple[dict[str, Any], SourceLocation, int, LoadedDocument]] = []
    scene_ids: dict[str, SourceLocation] = {}
    sources: list[Path] = []

    for document in documents:
        for source in document.sources:
            if source not in sources:
                sources.append(source)

        ordinary = {key: value for key, value in document.data.items() if key != "scenes"}
        _merge_values(
            merged,
            ordinary,
            path="$",
            target_provenance=provenance,
            incoming=document,
        )

        scenes = document.data.get("scenes", [])
        if not isinstance(scenes, list):
            _raise_conflict(
                "$.scenes",
                [],
                scenes,
                target_provenance=provenance,
                incoming=document,
            )
        for index, scene_value in enumerate(scenes):
            scene_path = f"$.scenes[{index}]"
            if not isinstance(scene_value, Mapping):
                scene_source = _location(document, scene_path).source
                raise MergeError(
                    f"Scene at {scene_path} in {scene_source} must be a mapping",
                    location=_location(document, scene_path),
                )
            scene = deepcopy(dict(scene_value))
            location = _location(document, scene_path)
            scene_id = scene.get("id")
            if isinstance(scene_id, str) and scene_id in scene_ids:
                first_location = scene_ids[scene_id]
                message = (
                    f"Duplicate scene id {scene_id!r} in "
                    f"{first_location.source} and {location.source}"
                )
                raise MergeConflictError(
                    message,
                    location=location,
                    context={
                        "path": f"{scene_path}.id",
                        "first_source": first_location.source,
                        "second_source": location.source,
                    },
                )
            if isinstance(scene_id, str):
                scene_ids[scene_id] = location
            scene_records.append((scene, location, index, document))

    if scene_records or any("scenes" in document.data for document in documents):
        ordered = sorted(
            ((scene, location, position) for scene, location, position, _ in scene_records),
            key=_scene_sort_key,
        )
        merged["scenes"] = [scene for scene, _, _ in ordered]
        provenance["$.scenes"] = SourceLocation(source="<merged>", yaml_path="$.scenes")
        record_by_identity = {
            id(scene): (position, document)
            for scene, _, position, document in scene_records
        }
        for new_index, (scene, _, _) in enumerate(ordered):
            old_index, document = record_by_identity[id(scene)]
            _append_scene_provenance(
                provenance,
                document,
                old_index=old_index,
                new_index=new_index,
            )

    provenance.setdefault("$", SourceLocation(source="<merged>", yaml_path="$"))
    return LoadedDocument(data=merged, sources=tuple(sources), provenance=provenance)
