"""Content-addressed provider-result caching with strict record validation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import tempfile
import weakref
from _thread import RLock
from collections import defaultdict
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Any

from .audio import decode_audio
from .errors import CapabilityError, ELScriptError, GenerationError
from .planner import RenderPlan
from .providers.base import (
    CharacterAlignment,
    GenerationResult,
    ProviderRequest,
    VoiceSegmentMetadata,
    request_diagnostic_context,
)

CACHE_IDENTITY_VERSION = "elscript-render-v1"
CACHE_RECORD_VERSION = 1
_MAX_CACHE_ENTRY_BYTES = 128 * 1024 * 1024
_FINGERPRINT_PREFIX = "sha256:"
_CACHE_LOCKS_GUARD = Lock()
_CACHE_LOCKS: weakref.WeakValueDictionary[str, RLock] = weakref.WeakValueDictionary()


def _shared_cache_lock(root: Path) -> RLock:
    key = os.path.normcase(str(root))
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _CACHE_LOCKS[key] = lock
        return lock


@dataclass(frozen=True, slots=True)
class PlanFingerprints:
    requests: Mapping[str, str]
    segments: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CacheLookup:
    status: str
    result: GenerationResult | None = None


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(child) for child in value)
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported cache identity value: {type(value).__name__}")


def _digest(value: Any) -> str:
    try:
        canonical = json.dumps(
            _plain(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise CapabilityError("Provider inputs cannot be represented in cache identity") from error
    return f"{_FINGERPRINT_PREFIX}{hashlib.sha256(canonical).hexdigest()}"


def _part_identity(request: ProviderRequest, part_index: int) -> dict[str, Any]:
    part = request.parts[part_index]
    segment = part.segment
    return {
        "voice_id": segment.voice_id,
        "provider_text": part.text,
        "translation_version": part.translation_version,
        "translated_features": sorted(feature.value for feature in part.features_used),
        "part_index": part.part_index,
        "part_count": part.part_count,
        "performance": asdict(segment.performance),
        "cues": segment.cues,
        "tags": segment.tags,
        "render_settings": segment.render_settings,
        "provider_options": segment.provider_options,
    }


def _request_identity(
    plan: RenderPlan,
    request: ProviderRequest,
    *,
    normalize_loudness: bool,
) -> dict[str, Any]:
    return {
        "identity_version": CACHE_IDENTITY_VERSION,
        "provider": plan.provider_id,
        "provider_adapter_version": plan.capability_version,
        "kind": request.kind.value,
        "model": request.model,
        "language": request.language,
        "output_format": request.output_format,
        "timestamps": request.timestamps,
        "streaming": request.streaming,
        "normalize_loudness": normalize_loudness,
        "dictionary_locators": [asdict(locator) for locator in request.dictionary_locators],
        "render_settings": request.render_settings,
        "provider_options": request.provider_options,
        "parts": [_part_identity(request, index) for index in range(len(request.parts))],
    }


def fingerprint_render_plan(
    plan: RenderPlan,
    *,
    normalize_loudness: bool,
    preserve_continuity: bool,
) -> PlanFingerprints:
    """Fingerprint planned requests plus only their material continuity neighbors."""

    base = [
        _digest(
            _request_identity(
                plan,
                request,
                normalize_loudness=normalize_loudness,
            )
        )
        for request in plan.requests
    ]
    requests: dict[str, str] = {}
    for index, request in enumerate(plan.requests):
        context: dict[str, str] = {"self": base[index]}
        previous_ids = request.provider_options.get("previous_request_ids", ())
        next_ids = request.provider_options.get("next_request_ids", ())
        previous_depth = max(
            1 if preserve_continuity else 0,
            len(previous_ids) if isinstance(previous_ids, (tuple, list)) else 0,
        )
        next_depth = max(
            1 if preserve_continuity else 0,
            len(next_ids) if isinstance(next_ids, (tuple, list)) else 0,
        )
        previous = [
            base[neighbor]
            for neighbor in range(max(0, index - previous_depth), index)
            if plan.requests[neighbor].scene_id == request.scene_id
        ]
        following = [
            base[neighbor]
            for neighbor in range(index + 1, min(len(plan.requests), index + next_depth + 1))
            if plan.requests[neighbor].scene_id == request.scene_id
        ]
        if previous:
            context["previous"] = _digest(previous)
        if following:
            context["next"] = _digest(following)
        requests[request.id] = _digest(
            {
                "identity_version": CACHE_IDENTITY_VERSION,
                "request": context,
            }
        )

    by_segment: dict[str, list[str]] = defaultdict(list)
    for request in plan.requests:
        fingerprint = requests[request.id]
        for logical_id in dict.fromkeys(part.logical_id for part in request.parts):
            by_segment[logical_id].append(fingerprint)
    segments = {
        logical_id: _digest(
            {
                "identity_version": CACHE_IDENTITY_VERSION,
                "request_fingerprints": fingerprints,
            }
        )
        for logical_id, fingerprints in by_segment.items()
    }
    return PlanFingerprints(
        requests=MappingProxyType(requests),
        segments=MappingProxyType(segments),
    )


def cache_root_for_output(output_root: Path) -> Path:
    """Use one local cache shared by sibling render destinations."""

    return output_root.parent / ".cache" / "elscript"


def _alignment_payload(alignment: CharacterAlignment | None) -> dict[str, Any] | None:
    if alignment is None:
        return None
    return {
        "characters": list(alignment.characters),
        "start_seconds": list(alignment.start_seconds),
        "end_seconds": list(alignment.end_seconds),
    }


def _result_payload(fingerprint: str, result: GenerationResult) -> dict[str, Any]:
    return {
        "version": CACHE_RECORD_VERSION,
        "fingerprint": fingerprint,
        "result": {
            "audio_base64": base64.b64encode(result.audio).decode("ascii"),
            "audio_sha256": hashlib.sha256(result.audio).hexdigest(),
            "output_format": result.output_format,
            "request_id": result.request_id,
            "duration_seconds": result.duration_seconds,
            "alignment": _alignment_payload(result.alignment),
            "normalized_alignment": _alignment_payload(result.normalized_alignment),
            "voice_segments": [asdict(item) for item in result.voice_segments],
        },
    }


def _finite_number(value: Any, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a finite number")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("expected a finite number")
    return converted


def _alignment_from_payload(value: Any) -> CharacterAlignment | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "characters",
        "start_seconds",
        "end_seconds",
    }:
        raise ValueError("invalid cached alignment")
    characters = value["characters"]
    starts = value["start_seconds"]
    ends = value["end_seconds"]
    if (
        not isinstance(characters, list)
        or not isinstance(starts, list)
        or not isinstance(ends, list)
        or any(not isinstance(character, str) for character in characters)
    ):
        raise ValueError("invalid cached alignment")
    start_values = tuple(_finite_number(item) for item in starts)
    end_values = tuple(_finite_number(item) for item in ends)
    if len(characters) != len(start_values) or len(characters) != len(end_values):
        raise ValueError("invalid cached alignment")
    if any(
        start is None or end is None or start < 0 or end < start
        for start, end in zip(start_values, end_values, strict=True)
    ):
        raise ValueError("invalid cached alignment")
    return CharacterAlignment(
        tuple(characters),
        tuple(item for item in start_values if item is not None),
        tuple(item for item in end_values if item is not None),
    )


def _optional_index(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid cached index")
    return value


def _voice_segments_from_payload(value: Any) -> tuple[VoiceSegmentMetadata, ...]:
    if not isinstance(value, list):
        raise ValueError("invalid cached voice segments")
    expected = {
        "voice_id",
        "start_seconds",
        "end_seconds",
        "part_index",
        "character_start_index",
        "character_end_index",
    }
    records: list[VoiceSegmentMetadata] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != expected:
            raise ValueError("invalid cached voice segment")
        voice_id = item["voice_id"]
        start = _finite_number(item["start_seconds"])
        end = _finite_number(item["end_seconds"])
        if (
            not isinstance(voice_id, str)
            or not voice_id
            or start is None
            or end is None
            or start < 0
            or end < start
        ):
            raise ValueError("invalid cached voice segment")
        character_start = _optional_index(item["character_start_index"])
        character_end = _optional_index(item["character_end_index"])
        if (
            character_start is not None
            and character_end is not None
            and character_end < character_start
        ):
            raise ValueError("invalid cached voice segment")
        records.append(
            VoiceSegmentMetadata(
                voice_id=voice_id,
                start_seconds=start,
                end_seconds=end,
                part_index=_optional_index(item["part_index"]),
                character_start_index=character_start,
                character_end_index=character_end,
            )
        )
    return tuple(records)


def _decode_record(
    payload: Any,
    *,
    fingerprint: str,
    output_format: str,
) -> GenerationResult:
    if not isinstance(payload, Mapping) or set(payload) != {
        "version",
        "fingerprint",
        "result",
    }:
        raise ValueError("invalid cache record")
    if payload["version"] != CACHE_RECORD_VERSION or payload["fingerprint"] != fingerprint:
        raise ValueError("cache identity mismatch")
    result = payload["result"]
    expected = {
        "audio_base64",
        "audio_sha256",
        "output_format",
        "request_id",
        "duration_seconds",
        "alignment",
        "normalized_alignment",
        "voice_segments",
    }
    if not isinstance(result, Mapping) or set(result) != expected:
        raise ValueError("invalid cached result")
    if result["output_format"] != output_format:
        raise ValueError("cached output format mismatch")
    encoded = result["audio_base64"]
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("invalid cached audio")
    audio = base64.b64decode(encoded, validate=True)
    digest = result["audio_sha256"]
    if not isinstance(digest, str) or hashlib.sha256(audio).hexdigest() != digest:
        raise ValueError("cached audio digest mismatch")
    decode_audio(audio, output_format)
    request_id = result["request_id"]
    if request_id is not None and not isinstance(request_id, str):
        raise ValueError("invalid cached request ID")
    duration = _finite_number(result["duration_seconds"], allow_none=True)
    if duration is not None and duration < 0:
        raise ValueError("invalid cached duration")
    return GenerationResult(
        audio=audio,
        output_format=output_format,
        request_id=request_id,
        duration_seconds=duration,
        alignment=_alignment_from_payload(result["alignment"]),
        normalized_alignment=_alignment_from_payload(result["normalized_alignment"]),
        voice_segments=_voice_segments_from_payload(result["voice_segments"]),
    )


def _fingerprint_digest(fingerprint: str) -> str:
    digest = fingerprint.removeprefix(_FINGERPRINT_PREFIX)
    if (
        not fingerprint.startswith(_FINGERPRINT_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("invalid cache fingerprint")
    return digest


class RenderCache:
    """Filesystem cache that treats every record as untrusted input."""

    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self._lock = _shared_cache_lock(self.root)

    def _bucket(self, fingerprint: str, *, create: bool) -> Path | None:
        digest = _fingerprint_digest(fingerprint)
        try:
            if self.root.is_symlink() or self.root.parent.is_symlink():
                return None
            if create:
                self.root.mkdir(parents=True, exist_ok=True)
            if not self.root.is_dir():
                return None
            root = self.root.resolve()
            bucket = self.root / digest[:2]
            if bucket.is_symlink():
                return None
            if create:
                bucket.mkdir(exist_ok=True)
            elif not bucket.exists():
                return bucket
            if not bucket.is_dir() or bucket.resolve().parent != root:
                return None
            return bucket
        except OSError:
            return None

    def _path(self, fingerprint: str, *, create: bool) -> Path | None:
        digest = _fingerprint_digest(fingerprint)
        bucket = self._bucket(fingerprint, create=create)
        return None if bucket is None else bucket / f"{digest}.json"

    def lookup(self, fingerprint: str, *, output_format: str) -> CacheLookup:
        with self._lock:
            return self._lookup(fingerprint, output_format=output_format)

    def _lookup(self, fingerprint: str, *, output_format: str) -> CacheLookup:
        try:
            path = self._path(fingerprint, create=False)
        except ValueError:
            return CacheLookup("corrupt")
        if path is None:
            return CacheLookup("miss" if not self.root.exists() else "unavailable")
        if path.is_symlink():
            return CacheLookup("corrupt")
        observed_file = False
        for _ in range(3):
            try:
                if not path.is_file():
                    continue
                observed_file = True
                if path.stat().st_size > _MAX_CACHE_ENTRY_BYTES:
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                result = _decode_record(
                    payload,
                    fingerprint=fingerprint,
                    output_format=output_format,
                )
                return CacheLookup("hit", result)
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
                TypeError,
                KeyError,
                binascii.Error,
                ELScriptError,
            ):
                continue
        return CacheLookup("corrupt" if observed_file else "miss")

    def store(self, fingerprint: str, result: GenerationResult) -> bool:
        with self._lock:
            return self._store(fingerprint, result)

    def _store(self, fingerprint: str, result: GenerationResult) -> bool:
        try:
            payload = _result_payload(fingerprint, result)
            _decode_record(
                payload,
                fingerprint=fingerprint,
                output_format=result.output_format,
            )
            encoded = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
            if len(encoded) > _MAX_CACHE_ENTRY_BYTES:
                return False
            path = self._path(fingerprint, create=True)
            if path is None or path.is_symlink():
                return False
            descriptor, temporary_name = tempfile.mkstemp(
                dir=path.parent,
                prefix=f".{path.stem}-",
                suffix=".tmp",
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            except BaseException:
                with suppress(OSError):
                    os.close(descriptor)
                with suppress(OSError):
                    temporary.unlink()
                raise
        except (OSError, ValueError, TypeError, binascii.Error, ELScriptError):
            return False
        return True


def generate_with_cache(
    plan: RenderPlan,
    provider_generate: Callable[[ProviderRequest], GenerationResult],
    cache: RenderCache,
    fingerprints: Mapping[str, str],
) -> tuple[dict[str, GenerationResult], dict[str, str], tuple[str, ...]]:
    """Resolve planned requests from cache or one provider call each."""

    results: dict[str, GenerationResult] = {}
    statuses: dict[str, str] = {}
    generated: list[str] = []
    for request in plan.requests:
        fingerprint = fingerprints[request.id]
        lookup = cache.lookup(fingerprint, output_format=request.output_format)
        if lookup.result is not None:
            results[request.id] = lookup.result
            statuses[request.id] = "hit"
            continue
        try:
            result = provider_generate(request)
        except ELScriptError as error:
            error.enrich_context(request_diagnostic_context(plan.provider_id, request))
            raise
        except Exception as error:
            raise GenerationError(
                "Provider generation failed unexpectedly",
                context=request_diagnostic_context(plan.provider_id, request),
            ) from error
        results[request.id] = result
        statuses[request.id] = lookup.status
        generated.append(request.id)
    return results, statuses, tuple(generated)
