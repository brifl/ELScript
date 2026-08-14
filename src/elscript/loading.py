"""Safe source loading with deterministic project discovery and provenance."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .domain import LoadedDocument, SourceLocation
from .errors import InputError, InvalidYamlError, SourceNotFoundError
from .merge import merge_documents

_YAML_SUFFIXES = frozenset({".yaml", ".yml"})
_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".codex",
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "audio",
        "build",
        "dist",
        "node_modules",
        "output",
        "outputs",
        "site",
        "venv",
    }
)


def _yaml_path(parent: str, key: object) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    return f"{parent}.{key}"


def _collect_provenance(
    value: object,
    *,
    source: str,
    path: str = "$",
    result: dict[str, SourceLocation] | None = None,
) -> dict[str, SourceLocation]:
    provenance = result if result is not None else {}
    provenance[path] = SourceLocation(source=source, yaml_path=path)
    if isinstance(value, Mapping):
        for key, child in value.items():
            _collect_provenance(
                child,
                source=source,
                path=_yaml_path(path, key),
                result=provenance,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_provenance(
                child,
                source=source,
                path=_yaml_path(path, index),
                result=provenance,
            )
    return provenance


def _parse_yaml(yaml_text: str, *, source_name: str) -> LoadedDocument:
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = SourceLocation(
            source=source_name,
            line=mark.line + 1 if mark is not None else None,
            column=mark.column + 1 if mark is not None else None,
        )
        raise InvalidYamlError(str(error), location=location) from error

    if not isinstance(parsed, Mapping):
        raise InputError(
            "ELScript YAML must contain a mapping at the document root",
            location=SourceLocation(source=source_name, yaml_path="$"),
        )

    document = deepcopy(dict(parsed))
    return LoadedDocument(
        data=document,
        sources=(Path(source_name),),
        provenance=_collect_provenance(document, source=source_name),
    )


def _load_yaml_file(path: Path) -> LoadedDocument:
    try:
        yaml_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise InputError(
            f"Unable to read ELScript source: {error}",
            location=SourceLocation(source=str(path)),
        ) from error
    return _parse_yaml(yaml_text, source_name=str(path))


def _is_hidden_or_ignored(relative_path: Path) -> bool:
    directory_parts = relative_path.parts[:-1]
    return any(
        part.startswith(".") or part.casefold() in _IGNORED_DIRECTORY_NAMES
        for part in directory_parts
    ) or relative_path.name.startswith(".")


def discover_yaml_files(
    source_root: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> tuple[Path, ...]:
    """Return eligible project YAML files in normalized relative-path order."""

    root = Path(source_root)
    if not root.exists():
        raise SourceNotFoundError(f"Source directory does not exist: {root}")
    if not root.is_dir():
        raise InputError(f"Directory source expected, got: {root}")

    resolved_root = root.resolve()
    resolved_output = Path(output_dir).resolve() if output_dir is not None else None
    discovered: list[tuple[str, Path]] = []

    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root)
        if _is_hidden_or_ignored(relative) or not candidate.is_file():
            continue
        if candidate.suffix.casefold() not in _YAML_SUFFIXES:
            continue

        resolved_candidate = candidate.resolve()
        if not resolved_candidate.is_relative_to(resolved_root):
            raise InputError(f"YAML source resolves outside the project directory: {candidate}")
        if resolved_output is not None and resolved_candidate.is_relative_to(resolved_output):
            continue
        discovered.append((relative.as_posix(), candidate))

    discovered.sort(key=lambda item: item[0])
    if not discovered:
        raise InputError(f"No .yaml or .yml files found under source directory: {root}")
    return tuple(path for _, path in discovered)


def _load_mapping(document: Mapping[str, Any]) -> LoadedDocument:
    copied = deepcopy(dict(document))
    source_name = "<document>"
    return LoadedDocument(
        data=copied,
        sources=(Path(source_name),),
        provenance=_collect_provenance(copied, source=source_name),
    )


def load_document(
    *,
    source: str | Path | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    output_dir: str | Path | None = None,
) -> LoadedDocument:
    """Load exactly one source form into a deterministic canonical document."""

    supplied = sum(value is not None for value in (source, yaml_text, document))
    if supplied != 1:
        raise InputError("Exactly one of source, yaml_text, or document must be supplied")

    if yaml_text is not None:
        return merge_documents((_parse_yaml(yaml_text, source_name="<yaml_text>"),))
    if document is not None:
        return merge_documents((_load_mapping(document),))

    source_path = Path(source)  # type: ignore[arg-type]
    if not source_path.exists():
        raise SourceNotFoundError(f"Source does not exist: {source_path}")
    if source_path.is_file():
        if source_path.suffix.casefold() not in _YAML_SUFFIXES:
            raise InputError(f"ELScript source file must end in .yaml or .yml: {source_path}")
        return merge_documents((_load_yaml_file(source_path),))
    if source_path.is_dir():
        fragments = tuple(
            _load_yaml_file(path)
            for path in discover_yaml_files(source_path, output_dir=output_dir)
        )
        return merge_documents(fragments)
    raise InputError(f"ELScript source is neither a regular file nor directory: {source_path}")
