# PLAN

## Execution frame

- Goal: Ship ELScript 1.0 as a trustworthy Python library and CLI that turns one file, a project directory, YAML text, or a Python mapping into expressive ElevenLabs audio, structured streaming chunks, and a safe machine-readable manifest.
- Context: `DESIGN.md` is the behavior contract and `README.md` is the intended operator experience; Stages 1–2 established the tested canonical source-to-audio/manifest pipeline.
- Constraints:
  - Keep one canonical load -> merge -> validate -> configure -> compile -> plan -> generate -> output pipeline for every entry point.
  - Preserve semantic authoring independently from provider request mechanics; unsupported intent must fail or produce an explicit coded warning.
  - Treat credentials, YAML, cache records, and output paths as security boundaries.
  - Keep the CLI a thin file-rendering wrapper; streaming remains Python-only.
- Done when: a fresh environment can install the package, pass the full automated suite, render the comprehensive single-file and multi-file examples through a deterministic fake provider, and pass an opt-in ElevenLabs smoke test when credentials are available.

## Architecture decisions

- Use a `src/elscript` Python package with explicit domain models between pipeline phases so source, provider, and output concerns do not leak across boundaries.
- Make parsing, merge, schema/reference validation, configuration resolution, compilation, and request planning pure or side-effect-free; isolate network, cache, and filesystem writes behind adapters.
- Model authored speech segments, provider requests, and output files as separate identities because their boundaries intentionally differ.
- Use a deterministic fake provider for required end-to-end acceptance; keep paid credentialed ElevenLabs calls opt-in.
- Build one synchronous core pipeline and adapt it deliberately for `stream()` and `astream()` so API and CLI behavior cannot drift.

## Stage 3 — Streaming, regeneration, and release hardening

Milestone: ELScript supports ordered sync/async streaming, safe incremental reuse, production diagnostics, and a releasable operator experience.

### 3.1 — Add structured synchronous and asynchronous streaming

- Objective:
  - Stream ordered, attributed audio and timeline events with natural backpressure and cancellation-safe async behavior.
- Deliverables:
  - `stream()` and `astream()` implementations in `src/elscript/api.py` over the canonical front half of the pipeline.
  - Provider streaming support and event normalization in the provider contracts/adapters.
  - Streaming state/order/backpressure/cancellation tests in `tests/test_streaming.py`.
- Acceptance:
  - [ ] Streaming accepts every source form and the same effective configuration as file rendering without requiring `output_dir`.
  - [ ] Consumers can identify scene, logical segment, ordinal, speaker, format, and final-segment boundaries for every audio chunk.
  - [ ] Pauses and markers are preserved consistently as documented ordered events or silence chunks.
  - [ ] Sync iteration applies consumer backpressure and async cancellation closes the active request without corrupting a later render.
  - [ ] Streaming writes no files unless a future explicit tee feature is separately requested.
- Demo commands:
  - `python -m pytest tests/test_streaming.py -q`
  - `python -m pytest tests/test_pipeline_equivalence.py -k streaming -q`
- Evidence:
  - Passing streaming tests and one compact chunk/event trace.

### 3.2 — Add content-addressed caching and incremental regeneration

- Objective:
  - Reuse provider results only when every material audio input and continuity dependency matches.
- Deliverables:
  - `src/elscript/cache.py` for canonical fingerprints, atomic cache records, validation, and lookup.
  - Request-context dependency tracking for grouping, neighbors, and stitching invalidation.
  - Cache observability in render results and manifests.
  - Cache hit/miss/corruption/invalidation tests in `tests/test_cache.py`.
- Acceptance:
  - [ ] Fingerprints include the design-mandated provider, prompt, settings, semantic translation, pronunciation, seed, language, normalization, context, and adapter versions.
  - [ ] Fingerprints exclude credentials, output directories/names, and unrelated metadata.
  - [ ] Exact repeats avoid provider calls and expose cache hits without changing output semantics.
  - [ ] Segment or grouping changes invalidate every continuity-dependent request while preserving unrelated reusable requests.
  - [ ] Corrupt/incomplete entries are ignored safely and writes are atomic under concurrent readers.
- Demo commands:
  - `python -m pytest tests/test_cache.py -q`
  - `python -m pytest tests/test_render_integration.py -k incremental -q`
- Evidence:
  - Passing cache tests and provider-call counts for repeat/selective-change renders.

### 3.3 — Harden security, diagnostics, and failure recovery

- Objective:
  - Make failures phase-specific, secret-safe, and operationally actionable across untrusted input, provider faults, and partial writes.
- Deliverables:
  - Stable warning-code registry and phase-aware diagnostic formatting.
  - Atomic render/output cleanup behavior for cancellation and mid-pipeline failures.
  - Adversarial security and fault-injection coverage in `tests/test_security.py` and `tests/test_failures.py`.
  - `docs/troubleshooting.md` mapping common diagnostics to corrections.
- Acceptance:
  - [ ] Each documented pipeline phase maps failures to a stable category/code with available source, YAML path, scene, character, segment, provider, and correction context.
  - [ ] Warnings cover only recoverable degradation; conflicts, unknown references, unsupported required intent, credentials, and voices remain errors.
  - [ ] Malicious YAML, aliases, logical IDs, filenames, and serialized metadata cannot instantiate objects, traverse paths, or leak credentials.
  - [ ] Provider failure or cancellation leaves no apparently complete manifest or corrupt final output and does not damage prior renders.
  - [ ] Troubleshooting guidance is verified against emitted codes and current CLI behavior.
- Demo commands:
  - `python -m pytest tests/test_security.py tests/test_failures.py -q`
  - `python -m pytest -q`
- Evidence:
  - Full-suite summary and one redacted fault diagnostic.

### 3.4 — Verify documentation and package release readiness

- Objective:
  - Make the designed public contract installable, discoverable, reproducible, and ready for a first versioned release.
- Deliverables:
  - README examples synchronized with tested public API/CLI behavior and supported ElevenLabs caveats.
  - `docs/` reference pages for ELScript 1.0 syntax, configuration, manifests, streaming, and provider capabilities.
  - Build metadata, license/package contents, changelog, and release checklist.
  - Documentation/example/package tests in `tests/test_docs_examples.py` and the build workflow.
- Acceptance:
  - [ ] Every README quick-start and comprehensive example is executed by tests against the canonical pipeline.
  - [ ] Public docs clearly separate portable semantics, provider escape hatches, supported degradation, and out-of-scope 1.0 features.
  - [ ] `sdist` and wheel build cleanly, contain required documentation/package assets, and install/import in a fresh environment.
  - [ ] Static/type/test checks pass from documented commands without repository-local undeclared state.
  - [ ] The release checklist includes the opt-in credentialed smoke and current provider-capability review without making paid calls part of default CI.
- Demo commands:
  - `python -m pytest tests/test_docs_examples.py -q`
  - `python -m build`
  - `python -m pytest -q`
- Evidence:
  - Passing docs/full-suite summary and names of built wheel/sdist artifacts.

## Non-blocking verification backlog

- [DEFERRED] Run a minimal real ElevenLabs speech/timestamp/dialogue smoke before the first release; owner: human-assisted agent; revisit when `ELEVENLABS_API_KEY` and approval to incur a small provider charge are available.
- Re-check current ElevenLabs model, endpoint, output-format, retention, and account-limit assumptions before release; update only the provider capability layer when upstream behavior has changed.
- Test Windows, macOS, and Linux path/audio behavior in release CI.
