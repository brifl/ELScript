"""Versioned ELScript semantic and request translation for ElevenLabs."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from ..domain import (
    CompiledScript,
    Diagnostic,
    DiagnosticSeverity,
    PipelinePhase,
    SpeechSegment,
)
from ..errors import CapabilityError, ProviderLimitError, UnsupportedModelFeatureError
from ..redaction import is_sensitive_key
from ..schema import Pronunciation, PronunciationTerm
from .base import (
    DictionaryLocator,
    EndpointCapabilities,
    PreparedSegment,
    ProviderCapabilities,
    ProviderFeature,
    ProviderRequest,
    RequestKind,
)

TRANSLATION_VERSION = "elevenlabs-prompt-v1"
ELEVEN_V3_MODEL = "eleven_v3"
_MAX_SEED = 4_294_967_295

_SPEECH_PROVIDER_OPTIONS = frozenset(
    {
        "voice_settings",
        "previous_text",
        "next_text",
        "previous_request_ids",
        "next_request_ids",
    }
)
_DIALOGUE_PROVIDER_OPTIONS = frozenset({"settings"})
_VOICE_SETTING_KEYS = frozenset(
    {"stability", "similarity_boost", "style", "speed", "use_speaker_boost"}
)
_PACE_TAGS: dict[str, str | None] = {
    "normal": None,
    "slow": "slowly",
    "slowly": "slowly",
    "measured": "measured",
    "fast": "quickly",
    "quick": "quickly",
    "quickly": "quickly",
}
_VOLUME_TAGS: dict[str, str | None] = {
    "normal": None,
    "quiet": "softly",
    "soft": "softly",
    "softly": "softly",
    "whisper": "whispers",
    "whispered": "whispers",
    "whispers": "whispers",
    "loud": "loudly",
    "loudly": "loudly",
    "shout": "shouts",
    "shouted": "shouts",
    "shouts": "shouts",
}


class ElevenLabsOperation(StrEnum):
    CREATE_SPEECH = "create_speech"
    CREATE_SPEECH_WITH_TIMESTAMPS = "create_speech_with_timestamps"
    STREAM_SPEECH = "stream_speech"
    STREAM_SPEECH_WITH_TIMESTAMPS = "stream_speech_with_timestamps"
    CREATE_DIALOGUE = "create_dialogue"
    CREATE_DIALOGUE_WITH_TIMESTAMPS = "create_dialogue_with_timestamps"
    STREAM_DIALOGUE = "stream_dialogue"
    STREAM_DIALOGUE_WITH_TIMESTAMPS = "stream_dialogue_with_timestamps"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(child) for child in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    return value


@dataclass(frozen=True, slots=True)
class ElevenLabsTranslation:
    prepared_segments: Mapping[str, PreparedSegment]
    dictionary_locators: tuple[DictionaryLocator, ...]
    warnings: tuple[Diagnostic, ...]
    version: str = TRANSLATION_VERSION


@dataclass(frozen=True, slots=True)
class ElevenLabsRequest:
    """Validated SDK-independent operation and material request inputs."""

    operation: ElevenLabsOperation
    voice_id: str | None
    body: Mapping[str, Any]
    query: Mapping[str, Any]
    translation_version: str
    warnings: tuple[Diagnostic, ...] = ()

    def fingerprint_inputs(self) -> dict[str, Any]:
        return {
            "provider": "elevenlabs",
            "operation": self.operation.value,
            "voice_id": self.voice_id,
            "translation_version": self.translation_version,
            "query": _plain(self.query),
            "body": _plain(self.body),
        }


def elevenlabs_capabilities() -> ProviderCapabilities:
    """Built-in preflight knowledge; live/account metadata may narrow it later."""

    common_features = frozenset(
        {
            ProviderFeature.STREAMING,
            ProviderFeature.TIMESTAMPS,
            ProviderFeature.PRONUNCIATION_DICTIONARIES,
            ProviderFeature.NATIVE_IPA,
            ProviderFeature.SEED,
            ProviderFeature.TEXT_NORMALIZATION,
            ProviderFeature.REQUEST_LOGGING_CONTROL,
            ProviderFeature.AUDIO_TAGS,
        }
    )
    return ProviderCapabilities(
        provider_id="elevenlabs",
        speech=EndpointCapabilities(
            features=common_features
            | {
                ProviderFeature.LANGUAGE_NORMALIZATION,
                ProviderFeature.REQUEST_STITCHING,
                ProviderFeature.VOICE_SETTINGS,
            },
            max_pronunciation_dictionaries=3,
            supported_provider_options=_SPEECH_PROVIDER_OPTIONS,
        ),
        dialogue=EndpointCapabilities(
            features=common_features | {ProviderFeature.SPEAKER_SEGMENTS},
            supported_models=frozenset({ELEVEN_V3_MODEL}),
            recommended_request_chars=2_000,
            max_unique_voices=10,
            max_pronunciation_dictionaries=3,
            supported_provider_options=_DIALOGUE_PROVIDER_OPTIONS,
        ),
        capability_version="elevenlabs-2026-08-14",
    )


def _warning(
    code: str,
    message: str,
    segment: SpeechSegment,
    *,
    field: str,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        message=message,
        severity=DiagnosticSeverity.WARNING,
        phase=PipelinePhase.CAPABILITY_VALIDATION,
        context={"segment_id": segment.id, "model": segment.model, "field": field},
    )


def _validate_tag(value: str, *, segment: SpeechSegment, field: str) -> str:
    if value != value.strip() or not value.strip():
        raise CapabilityError(
            f"ElevenLabs {field} values must not be empty or padded with whitespace",
            context={"segment_id": segment.id, "field": field},
        )
    if "[" in value or "]" in value or any(ord(character) < 32 for character in value):
        raise CapabilityError(
            f"ElevenLabs {field} value {value!r} contains invalid tag syntax",
            context={"segment_id": segment.id, "field": field},
        )
    return value


def _numeric_level(value: float, *, low: str, medium: str, high: str) -> str | None:
    if value == 0:
        return None
    if value <= 1 / 3:
        return low
    if value <= 2 / 3:
        return medium
    return high


def _semantic_tags(segment: SpeechSegment) -> tuple[tuple[str, ...], tuple[Diagnostic, ...]]:
    state = segment.performance
    has_direction = any(
        (
            state.emotion.casefold() != "neutral",
            state.intensity != 0,
            state.energy != 0,
            state.pace.casefold() != "normal",
            state.volume.casefold() != "normal",
            bool(state.delivery),
            state.accent is not None,
            bool(segment.cues),
            bool(segment.tags),
        )
    )
    if has_direction and segment.model != ELEVEN_V3_MODEL:
        raise UnsupportedModelFeatureError(
            f"Model {segment.model!r} cannot honor ELScript expressive directions",
            context={"segment_id": segment.id, "model": segment.model},
        )

    tags: list[str] = []
    warnings: list[Diagnostic] = []
    if state.emotion.casefold() != "neutral":
        tags.append(_validate_tag(state.emotion, segment=segment, field="emotion"))

    intensity = _numeric_level(
        state.intensity,
        low="subtle",
        medium="moderate intensity",
        high="intense",
    )
    if intensity is not None:
        tags.append(intensity)
        warnings.append(
            _warning(
                "ELEVENLABS_INTENSITY_APPROXIMATED",
                "Numeric intensity is approximated with an Eleven v3 audio tag",
                segment,
                field="intensity",
            )
        )

    energy = _numeric_level(
        state.energy,
        low="low energy",
        medium="steady energy",
        high="high energy",
    )
    if energy is not None:
        tags.append(energy)
        warnings.append(
            _warning(
                "ELEVENLABS_ENERGY_APPROXIMATED",
                "Numeric energy is approximated with an Eleven v3 audio tag",
                segment,
                field="energy",
            )
        )

    pace_key = state.pace.casefold()
    pace = _PACE_TAGS.get(pace_key, state.pace)
    if pace is not None:
        tags.append(_validate_tag(pace, segment=segment, field="pace"))
        if pace_key not in _PACE_TAGS:
            warnings.append(
                _warning(
                    "ELEVENLABS_SEMANTIC_TAG_EXPERIMENTAL",
                    f"Pace {state.pace!r} uses an experimental descriptive audio tag",
                    segment,
                    field="pace",
                )
            )

    volume_key = state.volume.casefold()
    volume = _VOLUME_TAGS.get(volume_key, state.volume)
    if volume is not None:
        tags.append(_validate_tag(volume, segment=segment, field="volume"))
        if volume_key not in _VOLUME_TAGS:
            warnings.append(
                _warning(
                    "ELEVENLABS_SEMANTIC_TAG_EXPERIMENTAL",
                    f"Volume {state.volume!r} uses an experimental descriptive audio tag",
                    segment,
                    field="volume",
                )
            )

    tags.extend(
        _validate_tag(value, segment=segment, field="delivery") for value in state.delivery
    )
    if state.accent is not None:
        accent = state.accent
        accent_tag = f"strong {accent}" if accent.casefold().endswith("accent") else (
            f"strong {accent} accent"
        )
        tags.append(_validate_tag(accent_tag, segment=segment, field="accent"))
        warnings.append(
            _warning(
                "ELEVENLABS_SEMANTIC_TAG_EXPERIMENTAL",
                f"Accent {accent!r} uses an experimental Eleven v3 audio tag",
                segment,
                field="accent",
            )
        )

    tags.extend(_validate_tag(value, segment=segment, field="cue") for value in segment.cues)
    tags.extend(_validate_tag(value, segment=segment, field="tag") for value in segment.tags)
    return tuple(tags), tuple(warnings)


def _ipa_text(value: str, *, term: str) -> str:
    ipa = value.strip()
    if len(ipa) >= 2 and ipa.startswith("/") and ipa.endswith("/"):
        ipa = ipa[1:-1]
    if not ipa or "/" in ipa or any(character in ipa for character in "\r\n"):
        raise CapabilityError(
            f"Pronunciation term {term!r} has invalid Eleven v3 IPA syntax"
        )
    return f"/{ipa}/"


def _term_replacement(
    term: str,
    pronunciation: PronunciationTerm,
    *,
    segment: SpeechSegment,
) -> tuple[str, Diagnostic | None]:
    if pronunciation.ipa is not None and segment.model == ELEVEN_V3_MODEL:
        return _ipa_text(pronunciation.ipa, term=term), None
    if pronunciation.say_as is not None:
        warning = None
        if pronunciation.ipa is not None:
            warning = _warning(
                "ELEVENLABS_IPA_ALIAS_FALLBACK",
                f"Model {segment.model!r} cannot use native IPA; say_as is used instead",
                segment,
                field=f"pronunciation.terms.{term}",
            )
        return pronunciation.say_as, warning
    raise UnsupportedModelFeatureError(
        f"Model {segment.model!r} cannot honor IPA pronunciation for term {term!r}",
        context={"segment_id": segment.id, "model": segment.model, "term": term},
    )


def _apply_pronunciation(
    text: str | None,
    pronunciation: Pronunciation,
    *,
    segment: SpeechSegment,
) -> tuple[str | None, tuple[Diagnostic, ...], tuple[str, ...]]:
    if text is None or not pronunciation.terms:
        return text, (), ()
    indexed_terms = list(enumerate(pronunciation.terms.items()))
    ordered_terms = sorted(indexed_terms, key=lambda item: (-len(item[1][0]), item[0]))
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(term) for _, (term, _) in ordered_terms) + r")(?!\w)"
    )
    matched_terms = {match.group(0) for match in pattern.finditer(text)}
    if not matched_terms:
        return text, (), ()
    replacements: dict[str, str] = {}
    warnings: list[Diagnostic] = []
    native_ipa_tokens: list[str] = []
    for _, (term, rule) in ordered_terms:
        if term not in matched_terms:
            continue
        replacement, warning = _term_replacement(term, rule, segment=segment)
        replacements[term] = replacement
        if rule.ipa is not None and segment.model == ELEVEN_V3_MODEL:
            native_ipa_tokens.append(replacement)
        if warning is not None:
            warnings.append(warning)
    return (
        pattern.sub(lambda match: replacements[match.group(0)], text),
        tuple(warnings),
        tuple(dict.fromkeys(native_ipa_tokens)),
    )


def _dictionary_locators(pronunciation: Pronunciation) -> tuple[DictionaryLocator, ...]:
    seen: dict[str, str] = {}
    locators: list[DictionaryLocator] = []
    for item in pronunciation.dictionaries:
        existing = seen.get(item.id)
        if existing is not None:
            if existing != item.version_id:
                raise CapabilityError(
                    f"Pronunciation dictionary {item.id!r} references conflicting versions",
                    context={"dictionary_id": item.id},
                )
            continue
        seen[item.id] = item.version_id
        locators.append(DictionaryLocator(item.id, item.version_id))
    if len(locators) > 3:
        raise ProviderLimitError(
            "ElevenLabs accepts at most 3 pronunciation dictionaries per request",
            context={"dictionary_count": len(locators), "limit": 3},
        )
    return tuple(locators)


def prepare_elevenlabs(
    compiled: CompiledScript,
    pronunciation: Pronunciation,
) -> ElevenLabsTranslation:
    """Translate full logical segments before the planner applies provider limits."""

    prepared: dict[str, PreparedSegment] = {}
    warnings: list[Diagnostic] = []
    for segment in compiled.segments:
        tags, tag_warnings = _semantic_tags(segment)
        text, pronunciation_warnings, native_ipa_tokens = _apply_pronunciation(
            segment.text,
            pronunciation,
            segment=segment,
        )
        prefix = " ".join(f"[{tag}]" for tag in tags)
        if not prefix and not text:
            raise CapabilityError(
                f"Segment {segment.id!r} produced no ElevenLabs prompt text",
                context={"segment_id": segment.id},
            )
        features: set[ProviderFeature] = set()
        if tags:
            features.add(ProviderFeature.AUDIO_TAGS)
        if native_ipa_tokens:
            features.add(ProviderFeature.NATIVE_IPA)
        prepared[segment.id] = PreparedSegment(
            text=text,
            translation_version=TRANSLATION_VERSION,
            prefix=prefix,
            features_used=frozenset(features),
            atomic_tokens=native_ipa_tokens,
        )
        warnings.extend(tag_warnings)
        warnings.extend(pronunciation_warnings)
    return ElevenLabsTranslation(
        prepared_segments=MappingProxyType(prepared),
        dictionary_locators=_dictionary_locators(pronunciation),
        warnings=tuple(warnings),
    )


def _validate_json_value(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CapabilityError(f"Provider option {path} must be finite")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CapabilityError(f"Provider option {path} keys must be strings")
            if is_sensitive_key(key):
                raise CapabilityError(
                    f"Credentials are not valid ElevenLabs request options at {path}.{key}"
                )
            _validate_json_value(child, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_json_value(child, path=f"{path}[{index}]")
        return
    raise CapabilityError(f"Provider option {path} is not JSON-compatible")


def _number(value: Any, *, path: str, minimum: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CapabilityError(f"Provider option {path} must be numeric")
    if not math.isfinite(float(value)) or not minimum <= value <= maximum:
        raise CapabilityError(
            f"Provider option {path} must be between {minimum} and {maximum}"
        )


def _validate_voice_settings(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise CapabilityError("Provider option voice_settings must be a mapping")
    unknown = set(value) - _VOICE_SETTING_KEYS
    if unknown:
        raise CapabilityError(
            f"Unsupported ElevenLabs voice setting(s): {', '.join(sorted(unknown))}"
        )
    for name in ("stability", "similarity_boost", "style"):
        if name in value:
            _number(value[name], path=f"voice_settings.{name}", minimum=0, maximum=1)
    if "speed" in value:
        _number(value["speed"], path="voice_settings.speed", minimum=0.7, maximum=1.2)
    if "use_speaker_boost" in value and not isinstance(value["use_speaker_boost"], bool):
        raise CapabilityError("Provider option voice_settings.use_speaker_boost must be boolean")


def _validate_continuity(value: Any, *, name: str) -> None:
    if name in {"previous_text", "next_text"}:
        if not isinstance(value, str) or not value:
            raise CapabilityError(f"Provider option {name} must be a non-empty string")
        return
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > 3
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise CapabilityError(
            f"Provider option {name} must contain at most 3 non-empty request IDs"
        )


def _validate_provider_options(request: ProviderRequest) -> dict[str, Any]:
    options = {
        str(key): _plain(value)
        for key, value in request.provider_options.items()
    }
    allowed = (
        _SPEECH_PROVIDER_OPTIONS
        if request.kind is RequestKind.SPEECH
        else _DIALOGUE_PROVIDER_OPTIONS
    )
    unknown = set(options) - allowed
    if unknown:
        raise UnsupportedModelFeatureError(
            f"{request.kind.value} request does not support provider option(s): "
            f"{', '.join(sorted(unknown))}",
            context={"request_id": request.id, "model": request.model},
        )
    if "voice_settings" in options:
        _validate_voice_settings(options["voice_settings"])
    for name in ("previous_text", "next_text", "previous_request_ids", "next_request_ids"):
        if name in options:
            _validate_continuity(options[name], name=name)
    for direction in ("previous", "next"):
        if f"{direction}_text" in options and f"{direction}_request_ids" in options:
            raise CapabilityError(
                f"Provider options {direction}_text and {direction}_request_ids are mutually "
                "exclusive because ElevenLabs ignores the text when request IDs are supplied"
            )
    if "settings" in options:
        if not isinstance(options["settings"], Mapping):
            raise CapabilityError("Provider option settings must be a mapping")
        _validate_json_value(options["settings"], path="settings")
    return options


def _operation(request: ProviderRequest) -> ElevenLabsOperation:
    if request.kind is RequestKind.SPEECH:
        if request.streaming:
            return (
                ElevenLabsOperation.STREAM_SPEECH_WITH_TIMESTAMPS
                if request.timestamps
                else ElevenLabsOperation.STREAM_SPEECH
            )
        return (
            ElevenLabsOperation.CREATE_SPEECH_WITH_TIMESTAMPS
            if request.timestamps
            else ElevenLabsOperation.CREATE_SPEECH
        )
    if request.streaming:
        return (
            ElevenLabsOperation.STREAM_DIALOGUE_WITH_TIMESTAMPS
            if request.timestamps
            else ElevenLabsOperation.STREAM_DIALOGUE
        )
    return (
        ElevenLabsOperation.CREATE_DIALOGUE_WITH_TIMESTAMPS
        if request.timestamps
        else ElevenLabsOperation.CREATE_DIALOGUE
    )


def build_elevenlabs_request(
    request: ProviderRequest,
    capabilities: ProviderCapabilities,
) -> ElevenLabsRequest:
    """Validate and materialize one planned request without performing I/O."""

    if capabilities.provider_id != "elevenlabs":
        raise CapabilityError("ElevenLabs request building requires ElevenLabs capabilities")
    endpoint = capabilities.for_kind(request.kind)
    if endpoint is None:
        raise UnsupportedModelFeatureError(
            f"ElevenLabs has no available {request.kind.value} endpoint"
        )
    versions = {part.translation_version for part in request.parts}
    if versions != {TRANSLATION_VERSION}:
        raise CapabilityError(
            f"Request {request.id!r} was not prepared by {TRANSLATION_VERSION}"
        )
    if any(part.text is None or not part.text for part in request.parts):
        raise CapabilityError(f"Request {request.id!r} contains empty provider text")
    if endpoint.supported_models is not None and request.model not in endpoint.supported_models:
        raise UnsupportedModelFeatureError(
            f"Model {request.model!r} does not support {request.kind.value} requests"
        )
    translated_features = frozenset(
        feature
        for part in request.parts
        for feature in part.features_used
    )
    if translated_features - endpoint.features:
        raise UnsupportedModelFeatureError(
            f"{request.kind.value} request contains unsupported translated features"
        )
    if len(request.dictionary_locators) > endpoint.max_pronunciation_dictionaries:
        raise ProviderLimitError(
            f"{request.kind.value} request has too many pronunciation dictionaries"
        )

    options = _validate_provider_options(request)
    enable_logging = bool(request.render_settings.get("enable_logging", True))
    stitching_options = {"previous_request_ids", "next_request_ids"} & options.keys()
    if not enable_logging and stitching_options:
        raise UnsupportedModelFeatureError(
            "ElevenLabs request stitching is unavailable when zero-retention mode is enabled",
            context={
                "request_id": request.id,
                "provider_options": sorted(stitching_options),
                "enable_logging": False,
            },
        )
    seed = request.render_settings.get("seed")
    if seed is not None and (
        isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= _MAX_SEED
    ):
        raise CapabilityError(f"ElevenLabs seed must be an integer from 0 to {_MAX_SEED}")

    body: dict[str, Any] = {
        "model_id": request.model,
        "pronunciation_dictionary_locators": [
            {
                "pronunciation_dictionary_id": item.id,
                "version_id": item.version_id,
            }
            for item in request.dictionary_locators
        ],
        "seed": seed,
        "apply_text_normalization": request.render_settings.get(
            "text_normalization", "auto"
        ),
    }
    if request.language is not None:
        body["language_code"] = request.language
    if request.kind is RequestKind.SPEECH:
        if len(request.parts) != 1:
            raise CapabilityError("A speech request must contain exactly one prepared part")
        body["text"] = request.parts[0].text
        body["apply_language_text_normalization"] = bool(
            request.render_settings.get("language_text_normalization", False)
        )
        body.update(options)
        voice_id: str | None = request.parts[0].segment.voice_id
    else:
        if request.model != ELEVEN_V3_MODEL:
            raise UnsupportedModelFeatureError(
                f"ElevenLabs dialogue requires model {ELEVEN_V3_MODEL!r}"
            )
        if request.render_settings.get("language_text_normalization", False):
            raise UnsupportedModelFeatureError(
                "ElevenLabs dialogue does not support language text normalization"
            )
        body["inputs"] = [
            {"text": part.text, "voice_id": part.segment.voice_id}
            for part in request.parts
        ]
        body.update(options)
        voice_id = None

    warnings: list[Diagnostic] = []
    language_normalization = bool(
        request.render_settings.get("language_text_normalization", False)
    )
    if request.kind is RequestKind.SPEECH and language_normalization:
        if request.language is not None and request.language.casefold() not in {"ja", "jpn"}:
            raise UnsupportedModelFeatureError(
                "ElevenLabs language text normalization is currently supported only for Japanese"
            )
        if request.language is None:
            warnings.append(
                Diagnostic(
                    code="ELEVENLABS_LANGUAGE_NORMALIZATION_UNVERIFIED",
                    message=(
                        "Language text normalization support cannot be pre-verified without "
                        "a language code"
                    ),
                    severity=DiagnosticSeverity.WARNING,
                    phase=PipelinePhase.CAPABILITY_VALIDATION,
                    context={"request_id": request.id, "model": request.model},
                )
            )
    if seed is not None:
        warnings.append(
            Diagnostic(
                code="ELEVENLABS_SEED_BEST_EFFORT",
                message="ElevenLabs treats seed determinism as best-effort",
                severity=DiagnosticSeverity.WARNING,
                phase=PipelinePhase.CAPABILITY_VALIDATION,
                context={"request_id": request.id, "model": request.model},
            )
        )
    return ElevenLabsRequest(
        operation=_operation(request),
        voice_id=voice_id,
        body=_freeze(body),
        query=_freeze(
            {
                "output_format": request.output_format,
                "enable_logging": enable_logging,
            }
        ),
        translation_version=TRANSLATION_VERSION,
        warnings=tuple(warnings),
    )
