"""Stable built-in diagnostic registry and operator-facing formatting."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from .domain import (
    Diagnostic,
    DiagnosticSeverity,
    PipelinePhase,
    SourceLocation,
)
from .errors import ELScriptError
from .redaction import redact


@dataclass(frozen=True, slots=True)
class DiagnosticDefinition:
    code: str
    severity: Literal["error", "warning"]
    phases: tuple[PipelinePhase, ...]
    correction: str


def _error(
    code: str,
    phases: PipelinePhase | tuple[PipelinePhase, ...],
    correction: str,
) -> DiagnosticDefinition:
    return DiagnosticDefinition(
        code,
        "error",
        phases if isinstance(phases, tuple) else (phases,),
        correction,
    )


def _warning(code: str, correction: str) -> DiagnosticDefinition:
    return DiagnosticDefinition(
        code,
        "warning",
        (PipelinePhase.CAPABILITY_VALIDATION,),
        correction,
    )


ERROR_REGISTRY: Mapping[str, DiagnosticDefinition] = MappingProxyType(
    {
        item.code: item
        for item in (
            _error(
                "ELSCRIPT_ERROR",
                tuple(PipelinePhase),
                "Use the phase and attached context to correct the input or environment.",
            ),
            _error(
                "INPUT_ERROR",
                PipelinePhase.SOURCE_DISCOVERY,
                "Supply exactly one readable ELScript source and valid input options.",
            ),
            _error(
                "SOURCE_NOT_FOUND",
                PipelinePhase.SOURCE_DISCOVERY,
                "Correct the source path or create the referenced file or directory.",
            ),
            _error(
                "INVALID_YAML",
                PipelinePhase.YAML_PARSING,
                "Correct the YAML syntax at the reported line and column.",
            ),
            _error(
                "MERGE_ERROR",
                PipelinePhase.LOGICAL_MERGE,
                "Remove incompatible project fragments and render again.",
            ),
            _error(
                "MERGE_CONFLICT",
                PipelinePhase.LOGICAL_MERGE,
                "Keep one value for the reported path or make duplicate definitions identical.",
            ),
            _error(
                "SCHEMA_ERROR",
                PipelinePhase.SCHEMA_VALIDATION,
                "Correct the reported ELScript field and value type.",
            ),
            _error(
                "VALIDATION_ERROR",
                (PipelinePhase.SCHEMA_VALIDATION, PipelinePhase.REFERENCE_VALIDATION),
                "Correct the reported YAML path or conflicting reference.",
            ),
            _error(
                "COMPILE_ERROR",
                PipelinePhase.SEMANTIC_COMPILATION,
                "Correct the script state transition identified in the diagnostic.",
            ),
            _error(
                "UNKNOWN_CHARACTER",
                (PipelinePhase.REFERENCE_VALIDATION, PipelinePhase.SEMANTIC_COMPILATION),
                "Define the character under characters or correct the speaker name.",
            ),
            _error(
                "UNKNOWN_PRESET",
                (PipelinePhase.REFERENCE_VALIDATION, PipelinePhase.SEMANTIC_COMPILATION),
                "Define the preset under presets or correct the preset reference.",
            ),
            _error(
                "INVALID_STATE",
                PipelinePhase.SEMANTIC_COMPILATION,
                "Correct the reported set, with, or reset state transition.",
            ),
            _error(
                "CAPABILITY_ERROR",
                PipelinePhase.CAPABILITY_VALIDATION,
                "Choose supported provider settings or remove the unsupported option.",
            ),
            _error(
                "UNSUPPORTED_MODEL_FEATURE",
                PipelinePhase.CAPABILITY_VALIDATION,
                "Choose a compatible model or remove the required unsupported feature.",
            ),
            _error(
                "UNSUPPORTED_OUTPUT_FORMAT",
                PipelinePhase.CAPABILITY_VALIDATION,
                "Select an output format supported by the planned provider endpoint.",
            ),
            _error(
                "PROVIDER_LIMIT",
                PipelinePhase.CAPABILITY_VALIDATION,
                "Reduce request size/options or split the authored content at a safe boundary.",
            ),
            _error(
                "PROVIDER_ERROR",
                PipelinePhase.PROVIDER_GENERATION,
                "Inspect the provider context and retry only after correcting the cause.",
            ),
            _error(
                "AUTHENTICATION_ERROR",
                PipelinePhase.PROVIDER_GENERATION,
                "Provide a valid provider credential through the documented secure channel.",
            ),
            _error(
                "RATE_LIMIT_ERROR",
                PipelinePhase.PROVIDER_GENERATION,
                "Wait for provider capacity or quota, then retry the render.",
            ),
            _error(
                "PROVIDER_ACCOUNT_ERROR",
                PipelinePhase.PROVIDER_GENERATION,
                "Resolve the provider account, billing, plan, or quota condition.",
            ),
            _error(
                "GENERATION_ERROR",
                PipelinePhase.PROVIDER_GENERATION,
                "Retry after checking provider availability and the reported request context.",
            ),
            _error(
                "AUDIO_ERROR",
                PipelinePhase.AUDIO_ASSEMBLY,
                "Verify provider audio and the selected output format.",
            ),
            _error(
                "DECODE_ERROR",
                PipelinePhase.AUDIO_ASSEMBLY,
                "Regenerate the affected provider result or remove the corrupt cache record.",
            ),
            _error(
                "ASSEMBLY_ERROR",
                PipelinePhase.AUDIO_ASSEMBLY,
                "Verify provider timing metadata and compatible audio formats.",
            ),
            _error(
                "OUTPUT_ERROR",
                PipelinePhase.OUTPUT_WRITING,
                "Use a writable, collision-free output directory.",
            ),
            _error(
                "FILENAME_COLLISION",
                PipelinePhase.OUTPUT_WRITING,
                "Rename colliding scene, segment, script, or character identifiers.",
            ),
            _error(
                "WRITE_ERROR",
                PipelinePhase.OUTPUT_WRITING,
                "Remove destination collisions and verify directory permissions and free space.",
            ),
        )
    }
)


WARNING_REGISTRY: Mapping[str, DiagnosticDefinition] = MappingProxyType(
    {
        item.code: item
        for item in (
            _warning(
                "ELEVENLABS_INTENSITY_APPROXIMATED",
                "Review the rendered delivery; adjust intensity or provider settings if needed.",
            ),
            _warning(
                "ELEVENLABS_ENERGY_APPROXIMATED",
                "Review the rendered delivery; adjust energy or provider settings if needed.",
            ),
            _warning(
                "ELEVENLABS_SEMANTIC_TAG_EXPERIMENTAL",
                "Audition the result because experimental provider tags may vary by model.",
            ),
            _warning(
                "ELEVENLABS_IPA_ALIAS_FALLBACK",
                "Review the alias pronunciation or configure a provider dictionary.",
            ),
            _warning(
                "ELEVENLABS_LANGUAGE_NORMALIZATION_UNVERIFIED",
                "Set an explicit supported language or disable language normalization.",
            ),
            _warning(
                "ELEVENLABS_SEED_BEST_EFFORT",
                "Do not rely on byte-identical provider output from seed alone.",
            ),
        )
    }
)


def make_warning(
    code: str,
    message: str,
    *,
    location: SourceLocation | None = None,
    context: Mapping[str, Any] | None = None,
) -> Diagnostic:
    """Create a warning whose code, severity, and phase cannot drift."""

    definition = WARNING_REGISTRY.get(code)
    if definition is None:
        raise ValueError(f"Unknown built-in warning code {code!r}")
    return Diagnostic(
        code=definition.code,
        message=message,
        severity=DiagnosticSeverity.WARNING,
        phase=definition.phases[0],
        location=location,
        context=redact(context or {}),
    )


def _location(location: SourceLocation | None) -> str:
    if location is None:
        return ""
    details = [location.source]
    if location.yaml_path:
        details.append(location.yaml_path)
    if location.line is not None:
        details.append(f"line {location.line}")
    if location.column is not None:
        details.append(f"column {location.column}")
    return f" at {', '.join(details)}"


def _context(value: Mapping[str, Any]) -> str:
    safe = redact(value)
    if not safe:
        return ""
    rendered = ", ".join(f"{key}={safe[key]!r}" for key in sorted(safe))
    return f" ({rendered})"


def format_error(error: ELScriptError) -> str:
    definition = ERROR_REGISTRY.get(error.code)
    correction = (
        definition.correction
        if definition is not None
        else "Use the diagnostic context to correct the input or environment."
    )
    phase = error.phase.value if error.phase is not None else "unknown"
    return (
        f"elscript: error [{phase}/{error.code}]: {error.message}"
        f"{_location(error.location)}{_context(error.context)}\n"
        f"Correction: {correction}\n"
    )


def format_warning(diagnostic: Diagnostic) -> str:
    definition = WARNING_REGISTRY.get(diagnostic.code)
    correction = f" Correction: {definition.correction}" if definition is not None else ""
    return (
        f"elscript: warning [{diagnostic.phase.value}/{diagnostic.code}]: "
        f"{diagnostic.message}{_location(diagnostic.location)}"
        f"{_context(diagnostic.context)}{correction}"
    )
