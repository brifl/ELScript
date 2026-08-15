"""Canonical public entry points for ELScript rendering and streaming."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import (
    RenderCache,
    cache_root_for_output,
    fingerprint_render_plan,
    generate_with_cache,
)
from .compiler import compile_document
from .config import EffectiveConfig, resolve_config
from .domain import (
    AudioChunk,
    CompiledScript,
    Diagnostic,
    RenderOptions,
    RenderResult,
    SceneResult,
    SegmentResult,
)
from .errors import CapabilityError, InputError
from .loading import load_document
from .manifest import (
    RenderManifest,
    build_manifest,
    preflight_manifest_output,
    write_manifest,
)
from .output import preflight_render_outputs, write_render_outputs
from .planner import RenderPlan, plan_render
from .providers.base import Provider
from .providers.elevenlabs import ElevenLabsProvider
from .providers.elevenlabs_prompt import (
    build_elevenlabs_request,
    prepare_elevenlabs,
)
from .providers.fake import FakeProvider
from .streaming import stream_render_plan
from .validation import validate_document

SourcePath = str | Path
OptionsInput = RenderOptions | Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _PreparedPipeline:
    config: EffectiveConfig
    compiled: CompiledScript
    provider: Provider
    plan: RenderPlan
    warnings: tuple[Diagnostic, ...]


def _validate_source_choice(
    source: SourcePath | None,
    yaml_text: str | None,
    document: Mapping[str, Any] | None,
) -> None:
    supplied = sum(value is not None for value in (source, yaml_text, document))
    if supplied != 1:
        raise InputError("Exactly one of source, yaml_text, or document must be supplied")


def _result_from_manifest(
    *,
    root: Path,
    manifest_path: Path | None,
    manifest: RenderManifest,
    warnings: tuple[Diagnostic, ...],
) -> RenderResult:
    scenes = tuple(
        SceneResult(
            id=scene.id,
            files=tuple(root / filename for filename in scene.files),
            duration_seconds=scene.duration_seconds,
        )
        for scene in manifest.scenes
    )
    segments = tuple(
        SegmentResult(
            id=segment.id,
            scene_id=segment.scene_id,
            ordinal=segment.ordinal,
            speaker=segment.speaker,
            file=root / segment.file if segment.file is not None else None,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            duration_seconds=segment.duration_seconds,
            provider_request_id=(
                segment.provider_request_ids[0] if segment.provider_request_ids else None
            ),
            render_fingerprint=segment.render_fingerprint,
        )
        for segment in manifest.segments
    )
    return RenderResult(
        files=tuple(root / item.path for item in manifest.files),
        manifest_path=manifest_path,
        duration_seconds=manifest.duration_seconds,
        scenes=scenes,
        segments=segments,
        provider_requests=len(manifest.provider_requests),
        cache_hits=sum(request.cache_status == "hit" for request in manifest.provider_requests),
        cache_misses=sum(request.cache_status != "hit" for request in manifest.provider_requests),
        warnings=warnings,
    )


def _prepare_pipeline(
    *,
    source: SourcePath | None,
    yaml_text: str | None,
    document: Mapping[str, Any] | None,
    options: OptionsInput | None,
    env_file: SourcePath | None,
    output_dir: SourcePath | None,
    streaming: bool,
) -> _PreparedPipeline:
    _validate_source_choice(source, yaml_text, document)
    loaded = load_document(
        source=source,
        yaml_text=yaml_text,
        document=document,
        output_dir=output_dir,
    )
    validated = validate_document(loaded)
    config = resolve_config(
        validated,
        options=options,
        source=source,
        env_file=env_file,
    )
    compiled = compile_document(validated, config)

    provider: Provider
    warnings: tuple[Diagnostic, ...] = ()
    if config.provider == "fake":
        provider = FakeProvider()
        plan = plan_render(
            compiled,
            config,
            provider.describe_capabilities(),
            streaming=streaming,
        )
    elif config.provider == "elevenlabs":
        provider = ElevenLabsProvider(config.credential)
        capabilities = provider.describe_capabilities()
        translation = prepare_elevenlabs(compiled, validated.pronunciation)
        plan = plan_render(
            compiled,
            config,
            capabilities,
            streaming=streaming,
            dictionaries=translation.dictionary_locators,
            prepared_segments=translation.prepared_segments,
        )
        request_warnings = tuple(
            warning
            for request in plan.requests
            for warning in build_elevenlabs_request(request, capabilities).warnings
        )
        warnings = (*translation.warnings, *request_warnings)
    else:
        raise CapabilityError(
            f"Unknown provider {config.provider!r}",
            context={"provider": config.provider},
        )
    return _PreparedPipeline(config, compiled, provider, plan, warnings)


def render(
    *,
    source: SourcePath | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    output_dir: SourcePath,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> RenderResult:
    """Render exactly one supported source form to files in ``output_dir``."""

    prepared = _prepare_pipeline(
        source=source,
        yaml_text=yaml_text,
        document=document,
        options=options,
        env_file=env_file,
        output_dir=output_dir,
        streaming=False,
    )

    preflight = preflight_render_outputs(
        prepared.compiled,
        prepared.plan,
        output_dir,
        output_format=prepared.config.output_format,
    )
    if prepared.config.manifest_enabled:
        preflight_manifest_output(prepared.compiled.script_id, preflight.root)

    fingerprints = fingerprint_render_plan(
        prepared.plan,
        normalize_loudness=prepared.config.normalize_loudness,
        preserve_continuity=prepared.config.chunking.preserve_continuity,
    )
    cache = RenderCache(cache_root_for_output(preflight.root))
    results, cache_statuses, generated_request_ids = generate_with_cache(
        prepared.plan,
        prepared.provider.generate,
        cache,
        fingerprints.requests,
    )
    outputs = write_render_outputs(
        prepared.compiled,
        prepared.plan,
        results,
        preflight.root,
        output_format=prepared.config.output_format,
        normalize_loudness=prepared.config.normalize_loudness,
    )
    try:
        build_manifest(
            prepared.compiled,
            prepared.plan,
            results,
            outputs,
            prepared.config,
            warnings=prepared.warnings,
            cache_statuses=cache_statuses,
            render_fingerprints=fingerprints.segments,
        )
        for request_id in generated_request_ids:
            if not cache.store(
                fingerprints.requests[request_id],
                results[request_id],
            ):
                cache_statuses[request_id] = f"{cache_statuses[request_id]}_unstored"
        manifest = build_manifest(
            prepared.compiled,
            prepared.plan,
            results,
            outputs,
            prepared.config,
            warnings=prepared.warnings,
            cache_statuses=cache_statuses,
            render_fingerprints=fingerprints.segments,
        )
        manifest_path = (
            write_manifest(manifest, preflight.root) if prepared.config.manifest_enabled else None
        )
    except BaseException:
        for path in outputs.files:
            with suppress(OSError):
                path.unlink()
        raise
    return _result_from_manifest(
        root=preflight.root,
        manifest_path=manifest_path,
        manifest=manifest,
        warnings=prepared.warnings,
    )


def render_yaml(
    yaml_text: str,
    *,
    output_dir: SourcePath,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> RenderResult:
    """Render YAML text through the canonical pipeline."""

    return render(
        yaml_text=yaml_text,
        output_dir=output_dir,
        options=options,
        env_file=env_file,
    )


def render_document(
    document: Mapping[str, Any],
    *,
    output_dir: SourcePath,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> RenderResult:
    """Render an already parsed mapping through the canonical pipeline."""

    return render(
        document=document,
        output_dir=output_dir,
        options=options,
        env_file=env_file,
    )


def stream(
    *,
    source: SourcePath | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> Iterator[AudioChunk]:
    """Stream attributed chunks through the canonical pipeline."""

    prepared = _prepare_pipeline(
        source=source,
        yaml_text=yaml_text,
        document=document,
        options=options,
        env_file=env_file,
        output_dir=None,
        streaming=True,
    )
    return stream_render_plan(
        prepared.plan,
        prepared.provider,
        output_format=prepared.config.output_format,
        include_source_text=prepared.config.include_source_text,
    )


def _next_chunk(iterator: Iterator[AudioChunk]) -> tuple[bool, AudioChunk | None]:
    try:
        return False, next(iterator)
    except StopIteration:
        return True, None


def _close_chunk_iterator(iterator: Iterator[AudioChunk]) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        close()


async def astream(
    *,
    source: SourcePath | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    options: OptionsInput | None = None,
    env_file: SourcePath | None = None,
) -> AsyncIterator[AudioChunk]:
    """Asynchronously stream attributed chunks through the canonical pipeline."""

    iterator = stream(
        source=source,
        yaml_text=yaml_text,
        document=document,
        options=options,
        env_file=env_file,
    )
    pending: asyncio.Task[tuple[bool, AudioChunk | None]] | None = None
    try:
        while True:
            pending = asyncio.create_task(asyncio.to_thread(_next_chunk, iterator))
            done, chunk = await asyncio.shield(pending)
            pending = None
            if done:
                return
            assert chunk is not None
            yield chunk
    finally:
        if pending is not None:
            with suppress(asyncio.CancelledError, Exception):
                await pending
        with suppress(Exception):
            await asyncio.to_thread(_close_chunk_iterator, iterator)
