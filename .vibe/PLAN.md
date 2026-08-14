# PLAN

## Execution frame

- Goal: Ship ELScript 1.0 as a trustworthy Python library and CLI that turns one file, a project directory, YAML text, or a Python mapping into expressive ElevenLabs audio, structured streaming chunks, and a safe machine-readable manifest.
- Context: `DESIGN.md` is the behavior contract and `README.md` is the intended operator experience; the repository currently has no package, tests, build manifest, or implementation.
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

## Stage 1 — Deterministic authoring and compilation core

Milestone: All supported source forms produce the same validated, fully resolved, provider-neutral timeline without network access.

### 1.1 — Bootstrap the package and public contracts

- Objective:
  - Install ELScript as a Python package with stable public result, option, chunk, diagnostic, and error contracts ready for the pipeline.
- Deliverables:
  - `pyproject.toml` with `src` packaging, `elscript` console entry point, runtime dependencies, and test tooling.
  - `src/elscript/domain.py` containing typed public and internal boundary models such as `RenderOptions`, `RenderResult`, `AudioChunk`, warnings, and phase artifacts.
  - `src/elscript/errors.py` containing the documented programmatically distinguishable error hierarchy.
  - `src/elscript/__init__.py` and `src/elscript/cli.py` exposing the intended import surface and useful CLI help.
  - Focused public-contract tests under `tests/`.
- Acceptance:
  - [ ] `pip install -e '.[dev]'` succeeds in a clean virtual environment on the supported Python baseline.
  - [ ] `import elscript` exposes `render`, `render_yaml`, `render_document`, `stream`, `astream`, `RenderResult`, and `AudioChunk` without importing provider SDK internals.
  - [ ] Error subclasses can be caught by input, merge, schema, compile, capability, provider, audio, and output category.
  - [ ] `elscript --help` documents file/directory input and file-render options and does not advertise CLI streaming.
- Demo commands:
  - `python -m pip install -e '.[dev]'`
  - `python -m pytest tests/test_public_contracts.py -q`
  - `elscript --help`
- Evidence:
  - Test summary plus the first line of `elscript --help`.
  - Commit hash for the package bootstrap.

### 1.2 — Load and logically merge every source form

- Objective:
  - Convert files, directories, YAML text, and mappings into one canonical document with deterministic provenance-aware merge behavior.
- Deliverables:
  - `src/elscript/loading.py` for safe YAML parsing, source selection, recursive discovery, exclusions, and provenance.
  - `src/elscript/merge.py` for section-aware deep merge, stable list rules, scene uniqueness, and ordering.
  - Source and merge fixtures covering single-file, split-project, conflict, traversal-order, and invalid-input cases.
  - Unit and equivalence tests in `tests/test_loading.py` and `tests/test_merge.py`.
- Acceptance:
  - [ ] Exactly one of `source`, `yaml_text`, or `document` is required, and all three converge on the same canonical representation.
  - [ ] YAML uses safe construction and rejects non-mapping roots with source-aware `InputError` diagnostics.
  - [ ] Directory discovery is recursive, excludes hidden/output locations, and is independent of filesystem enumeration order.
  - [ ] Mapping conflicts name the logical path and both sources; identical leaves merge and duplicate scene IDs fail.
  - [ ] Final scene ordering follows explicit order, normalized source path, and in-file position deterministically.
- Demo commands:
  - `python -m pytest tests/test_loading.py tests/test_merge.py -q`
  - `python -m pytest tests/test_pipeline_equivalence.py -k source_forms -q`
- Evidence:
  - Passing loader/merge summary and one asserted conflict diagnostic.

### 1.3 — Validate ELScript 1.0 documents and references

- Objective:
  - Reject invalid or ambiguous ELScript documents before compilation with actionable paths and stable diagnostic codes.
- Deliverables:
  - `src/elscript/schema.py` for top-level, render, pronunciation, preset, character, scene, entry, and export validation.
  - `src/elscript/validation.py` for version, character, preset, ID, range, and cross-reference checks.
  - Valid and invalid contract fixtures derived from the complete `DESIGN.md` example.
  - Schema and reference tests in `tests/test_schema.py` and `tests/test_validation.py`.
- Acceptance:
  - [ ] The comprehensive example validates, including scalar speech, structured `say`, `set`, `with`, `reset`, `cue`, `tags`, `pause`, `note`, and `marker` forms.
  - [ ] Unknown core fields, unsupported schema versions, malformed values, and performance values outside defined ranges fail before rendering.
  - [ ] Unknown characters/presets, duplicate logical IDs, and missing required voice IDs produce actionable source/YAML paths.
  - [ ] The `api` escape hatch preserves structured provider data without accepting credentials or weakening core schema checks.
- Demo commands:
  - `python -m pytest tests/test_schema.py tests/test_validation.py -q`
  - `python -m pytest tests/test_design_examples.py -k validation -q`
- Evidence:
  - Passing validation summary and one representative path-rich failure.

### 1.4 — Resolve layered configuration and credentials

- Objective:
  - Produce an immutable effective configuration with exact leaf-level precedence and redacted credential handling.
- Deliverables:
  - `src/elscript/config.py` for defaults, `.env` discovery, process environment, YAML, and explicit option resolution.
  - Typed effective render/export/provider configuration integrated with the validated document.
  - Redaction utilities shared by diagnostics, manifests, and cache identity.
  - Precedence, falsey-value, discovery, and secret-leak tests in `tests/test_config.py`.
- Acceptance:
  - [ ] Explicit call/CLI values override YAML, process environment, `.env`, and defaults leaf-by-leaf in that order.
  - [ ] Explicit `false`, zero, and empty values do not fall through to lower layers.
  - [ ] `.env` discovery follows the source-root then current-directory contract, while process environment wins.
  - [ ] Credentials can be supplied explicitly or through `ELEVENLABS_API_KEY` and never appear in representations, errors, manifests, or fingerprint inputs.
  - [ ] Diagnostics identify the selected `.env` path without exposing its contents.
- Demo commands:
  - `python -m pytest tests/test_config.py -q`
  - `python -m pytest tests/test_security.py -k credential -q`
- Evidence:
  - Passing precedence matrix and credential-redaction tests.

### 1.5 — Compile sticky state into a canonical timeline

- Objective:
  - Compile validated scenes into stable speech segments and ordered non-speech events with fully resolved semantic and provider state.
- Deliverables:
  - `src/elscript/compiler.py` implementing baselines, scene inheritance, `set`, `with`, `reset`, structured speech, cues, and tags.
  - Deterministic logical ID and global speech-ordinal generation.
  - Provider-neutral timeline models for speech, pause, marker, and note events.
  - State-machine, ordering, and example-based tests in `tests/test_compiler.py`.
- Acceptance:
  - [ ] Persistent state is isolated per character, resets to the effective baseline, and crosses scenes only when explicitly inherited.
  - [ ] Utterance- and segment-level temporary state observes the documented precedence and never mutates persistent state.
  - [ ] Structured `say` preserves state-only commands and authored vocal ordering, including cue-only segments.
  - [ ] Notes are never vocalized; pauses and markers remain ordered timeline events and do not consume speech ordinals.
  - [ ] Generated IDs and global ordinals are deterministic, while explicit IDs remain unchanged.
  - [ ] The comprehensive example compiles to an inspectable timeline with expected final character states.
- Demo commands:
  - `python -m pytest tests/test_compiler.py -q`
  - `python -m pytest tests/test_design_examples.py -k compiler -q`
- Evidence:
  - Passing compiler summary and a compact timeline snapshot for the comprehensive example.

## Stage 2 — ElevenLabs rendering and file outputs

Milestone: Python and CLI users can render all three output modes through one pipeline with validated ElevenLabs requests, safe files, and complete manifests.

### 2.1 — Define capabilities and deterministic render planning

- Objective:
  - Turn compiled timelines into provider requests without conflating authored segments, request groups, or output boundaries.
- Deliverables:
  - `src/elscript/providers/base.py` defining provider, capability, generation, metadata, and streaming contracts.
  - `src/elscript/planner.py` implementing `auto`, `speech`, and `dialogue` strategies plus grouping and split rules.
  - A deterministic fake provider used by integration tests without network or charges.
  - Planner/capability tests in `tests/test_planner.py`.
- Acceptance:
  - [ ] Planning honors scene boundaries, explicit pauses, model/settings/dictionary compatibility, output mode, and streaming mode.
  - [ ] Dialogue groups never exceed configured/provider character or unique-voice limits and preserve speaker/segment identity.
  - [ ] A logical segment split for provider limits retains ordered subparts under one logical ID.
  - [ ] Unsupported requested capabilities fail before generation unless an explicit coded degradation policy applies.
  - [ ] Identical inputs produce structurally identical plans.
- Demo commands:
  - `python -m pytest tests/test_planner.py -q`
  - `python -m pytest tests/test_capabilities.py -q`
- Evidence:
  - Passing planner tests and one readable multi-speaker plan snapshot.

### 2.2 — Translate semantics and pronunciation for ElevenLabs

- Objective:
  - Convert resolved semantic intent into validated ElevenLabs text, tags, pronunciation, and endpoint options without silent loss.
- Deliverables:
  - `src/elscript/providers/elevenlabs_prompt.py` for versioned semantic-to-provider translation.
  - Exact, boundary-safe pronunciation term substitution and dictionary locator handling.
  - Scoped raw `api` option resolution and model/endpoint validation.
  - Translation and warning tests in `tests/test_elevenlabs_prompt.py`.
- Acceptance:
  - [ ] Eleven v3 emotion, intensity, energy, pace, volume, delivery, cues, and authored tags preserve deterministic authored order.
  - [ ] Exact/case-sensitive pronunciation matching avoids substring corruption and v3 IPA compiles to native form.
  - [ ] Dictionary limits and raw provider settings are validated for the selected endpoint/model before generation.
  - [ ] Unsupported semantic intent yields a stable warning or capability error, never silent omission.
  - [ ] Translation version and all material provider inputs are available to render identity.
- Demo commands:
  - `python -m pytest tests/test_elevenlabs_prompt.py -q`
  - `python -m pytest tests/test_pronunciation.py -q`
- Evidence:
  - Passing translation tests and one semantic-to-request snapshot.

### 2.3 — Implement the ElevenLabs generation adapter

- Objective:
  - Execute planned speech/dialogue requests through ElevenLabs normal and timestamp endpoints with stable result and error translation.
- Deliverables:
  - `src/elscript/providers/elevenlabs.py` implementing capability description, request execution, and metadata extraction.
  - Transport boundary supporting deterministic mocked HTTP/SDK contract tests.
  - Continuity support for context text and request stitching where compatible.
  - Adapter tests in `tests/test_elevenlabs_provider.py` with recorded request/response shapes and no live calls.
- Acceptance:
  - [ ] Speech and dialogue plans select the correct normal or timestamp operation and send every validated material option.
  - [ ] Audio bytes, request IDs, character alignment, normalized alignment, and voice segments are normalized into provider-neutral results.
  - [ ] Authentication, rate-limit, capability/account, and generation failures map to stable ELScript error categories with secrets redacted.
  - [ ] Continuity data is bounded to provider limits and disabled when incompatible with zero-retention behavior.
  - [ ] The automated suite performs no network calls and cannot incur provider charges.
- Demo commands:
  - `python -m pytest tests/test_elevenlabs_provider.py -q`
  - `python -m pytest tests/test_security.py -k provider -q`
- Evidence:
  - Passing adapter contract summary and representative request-shape assertion.

### 2.4 — Assemble audio and write safe output modes

- Objective:
  - Materialize valid `single`, `scene`, and `segment` audio outputs with deterministic timing, silence insertion, and path containment.
- Deliverables:
  - `src/elscript/audio.py` for decode, concatenation, explicit silence, format handling, and optional normalization.
  - `src/elscript/output.py` for naming, sanitization, collision detection, containment, directories, and overwrite policy.
  - Small deterministic audio fixtures and tests in `tests/test_audio.py` and `tests/test_output.py`.
- Acceptance:
  - [ ] Single and scene modes preserve authored order and insert explicit pauses within encoding tolerance.
  - [ ] Segment mode emits one valid file per audible speech segment and no standalone pause files.
  - [ ] Filenames use the documented script/scene/global ordinal/logical speaker rules and remain lexically sortable above 9,999 segments.
  - [ ] Malicious or colliding IDs cannot escape `output_dir`, and the default overwrite policy refuses unrelated existing files.
  - [ ] Output format/extension and optional loudness normalization are deterministic and reported as effective settings.
- Demo commands:
  - `python -m pytest tests/test_audio.py tests/test_output.py -q`
  - `python -m pytest tests/test_security.py -k output_path -q`
- Evidence:
  - Passing audio/output summary and a generated three-mode file listing.

### 2.5 — Emit manifests with global timeline metadata

- Objective:
  - Write a privacy-aware manifest that lets downstream tools reconstruct files, segments, provider requests, timings, pauses, and markers.
- Deliverables:
  - `src/elscript/manifest.py` with versioned serializable manifest models.
  - Provider-local to output-global timing/alignment translation.
  - Configurable source-text and provider metadata retention.
  - Manifest contract tests in `tests/test_manifest.py`.
- Acceptance:
  - [ ] Every output mode records generated files, durations, scenes, logical segments, provider requests, warnings, and cache status where applicable.
  - [ ] Segment records distinguish logical ID, ordinal, provider request ID, and resolved sanitized filename.
  - [ ] Pause and marker events retain authored order and best-known global time without requiring silent segment files.
  - [ ] Character/normalized alignment and dialogue voice segments translate correctly across assembled request boundaries.
  - [ ] Source text can be omitted and secrets are absent under recursive redaction checks.
- Demo commands:
  - `python -m pytest tests/test_manifest.py -q`
  - `python -m pytest tests/test_security.py -k manifest -q`
- Evidence:
  - Passing manifest tests and a bounded example manifest path.

### 2.6 — Wire canonical render APIs and the thin CLI

- Objective:
  - Deliver the README render experience through one end-to-end pipeline for every source form and all file output modes.
- Deliverables:
  - `src/elscript/api.py` implementing `render`, `render_yaml`, and `render_document` through the canonical pipeline.
  - `src/elscript/cli.py` file-render command with documented overrides, exit codes, warnings, and concise diagnostics.
  - End-to-end fake-provider fixtures for the comprehensive single-file and split-project examples.
  - Integration and CLI tests in `tests/test_render_integration.py` and `tests/test_cli.py`.
- Acceptance:
  - [ ] File, directory, YAML-text, mapping, convenience functions, and CLI calls share identical compiled plans and output semantics.
  - [ ] The comprehensive example renders valid single, scene, and segment assets plus manifests using the fake provider.
  - [ ] CLI overrides obey configuration precedence and errors exit nonzero with phase, source/path context, and an actionable correction.
  - [ ] `RenderResult` exposes paths, duration, scenes, segments, provider-request count, and warnings without requiring manifest parsing.
  - [ ] CLI has no alternate parser/compiler/provider path and exposes no streaming switch.
- Demo commands:
  - `python -m pytest tests/test_render_integration.py tests/test_cli.py -q`
  - `elscript tests/fixtures/signal_below --output build/demo-audio --mode segment`
  - `python -m pytest -q`
- Evidence:
  - Full-suite summary plus demo output/manifest paths.

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
- Re-check current ElevenLabs model, endpoint, output-format, retention, and account-limit assumptions during Stage 2.3 and again before release; update only the provider capability layer when upstream behavior has changed.
- Test Windows, macOS, and Linux path/audio behavior in release CI once Stage 2 establishes the runtime audio dependency.
