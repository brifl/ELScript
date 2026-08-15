"""Programmatically distinguishable ELScript error hierarchy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Self

from .domain import PipelinePhase, SourceLocation
from .redaction import redact


class ELScriptError(Exception):
    """Base exception with stable code, phase, source location, and safe context."""

    default_code: ClassVar[str] = "ELSCRIPT_ERROR"
    default_phase: ClassVar[PipelinePhase | None] = None

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        phase: PipelinePhase | None = None,
        location: SourceLocation | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.phase = phase or self.default_phase
        self.location = location
        self.context = redact(context or {})

    def __str__(self) -> str:
        parts = [f"{self.code}: {self.message}"]
        if self.location is not None:
            location = self.location.source
            if self.location.yaml_path:
                location = f"{location}:{self.location.yaml_path}"
            parts.append(f"at {location}")
        if self.context:
            rendered = ", ".join(f"{key}={value!r}" for key, value in self.context.items())
            parts.append(f"({rendered})")
        return " ".join(parts)

    def enrich_context(self, context: Mapping[str, Any]) -> Self:
        """Attach safe higher-level attribution without replacing specific details."""

        inherited = redact(context)
        self.context = {**inherited, **self.context}
        return self


class InputError(ELScriptError):
    default_code = "INPUT_ERROR"
    default_phase = PipelinePhase.SOURCE_DISCOVERY


class SourceNotFoundError(InputError):
    default_code = "SOURCE_NOT_FOUND"


class InvalidYamlError(InputError):
    default_code = "INVALID_YAML"
    default_phase = PipelinePhase.YAML_PARSING


class MergeError(ELScriptError):
    default_code = "MERGE_ERROR"
    default_phase = PipelinePhase.LOGICAL_MERGE


class MergeConflictError(MergeError):
    default_code = "MERGE_CONFLICT"


class SchemaError(ELScriptError):
    default_code = "SCHEMA_ERROR"
    default_phase = PipelinePhase.SCHEMA_VALIDATION


class ValidationError(SchemaError):
    default_code = "VALIDATION_ERROR"


class CompileError(ELScriptError):
    default_code = "COMPILE_ERROR"
    default_phase = PipelinePhase.SEMANTIC_COMPILATION


class UnknownCharacterError(CompileError):
    default_code = "UNKNOWN_CHARACTER"


class UnknownPresetError(CompileError):
    default_code = "UNKNOWN_PRESET"


class InvalidStateError(CompileError):
    default_code = "INVALID_STATE"


class CapabilityError(ELScriptError):
    default_code = "CAPABILITY_ERROR"
    default_phase = PipelinePhase.CAPABILITY_VALIDATION


class UnsupportedModelFeatureError(CapabilityError):
    default_code = "UNSUPPORTED_MODEL_FEATURE"


class UnsupportedOutputFormatError(CapabilityError):
    default_code = "UNSUPPORTED_OUTPUT_FORMAT"


class ProviderLimitError(CapabilityError):
    default_code = "PROVIDER_LIMIT"


class ProviderError(ELScriptError):
    default_code = "PROVIDER_ERROR"
    default_phase = PipelinePhase.PROVIDER_GENERATION


class AuthenticationError(ProviderError):
    default_code = "AUTHENTICATION_ERROR"


class RateLimitError(ProviderError):
    default_code = "RATE_LIMIT_ERROR"


class ProviderAccountError(ProviderError):
    default_code = "PROVIDER_ACCOUNT_ERROR"


class GenerationError(ProviderError):
    default_code = "GENERATION_ERROR"


class AudioError(ELScriptError):
    default_code = "AUDIO_ERROR"
    default_phase = PipelinePhase.AUDIO_ASSEMBLY


class DecodeError(AudioError):
    default_code = "DECODE_ERROR"


class AssemblyError(AudioError):
    default_code = "ASSEMBLY_ERROR"


class OutputError(ELScriptError):
    default_code = "OUTPUT_ERROR"
    default_phase = PipelinePhase.OUTPUT_WRITING


class FilenameCollisionError(OutputError):
    default_code = "FILENAME_COLLISION"


class WriteError(OutputError):
    default_code = "WRITE_ERROR"
