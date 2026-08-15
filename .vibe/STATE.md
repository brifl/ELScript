# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 3
- Checkpoint: 3.3
- Status: IN_REVIEW  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Make failures phase-specific, secret-safe, and operationally actionable across untrusted input, provider faults, and partial writes.

## Deliverables (current checkpoint)

- Stable warning-code registry and phase-aware diagnostic formatting.
- Atomic render/output cleanup behavior for cancellation and mid-pipeline failures.
- Adversarial security and fault-injection coverage in `tests/test_security.py` and `tests/test_failures.py`.
- `docs/troubleshooting.md` mapping common diagnostics to corrections.

## Acceptance (current checkpoint)

- [ ] Each documented pipeline phase maps failures to a stable category/code with available source, YAML path, scene, character, segment, provider, and correction context.
- [ ] Warnings cover only recoverable degradation; conflicts, unknown references, unsupported required intent, credentials, and voices remain errors.
- [ ] Malicious YAML, aliases, logical IDs, filenames, and serialized metadata cannot instantiate objects, traverse paths, or leak credentials.
- [ ] Provider failure or cancellation leaves no apparently complete manifest or corrupt final output and does not damage prior renders.
- [ ] Troubleshooting guidance is verified against emitted codes and current CLI behavior.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 2 into `.vibe/HISTORY.md`; the canonical source-to-audio/manifest pipeline passes 171 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 3.1 for structured synchronous and asynchronous streaming; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Began the canonical sync/async stream implementation with typed provider metadata, ordered timeline events, demand-driven iteration, and explicit dialogue attribution.
- 2026-08-14: Implemented checkpoint 3.1 in `0b831cf`; auto-mode streams independently attributable speech requests, explicit dialogue is split using provider voice timing, and async iteration closes active work on cancellation.
- 2026-08-14: Review FAIL: the urllib production transport buffers `response.read()` before provider iteration, so real ElevenLabs calls do not yet provide network-level streaming or close propagation.
- 2026-08-14: Resolved ISSUE-301 in `ed77a8d` with incremental urllib reads, arbitrary-boundary timestamp JSON decoding, one-chunk final lookahead, and socket-close propagation.
- 2026-08-14: Review PASS for checkpoint 3.1 after 180-test regression evidence and targeted production transport, close, cancellation, malformed-data, and redaction probes; auto-advanced to checkpoint 3.2.
- 2026-08-14: Began checkpoint 3.2 with request-granular content identity, conservative immediate-neighbor continuity dependencies, and a local atomic cache shared by sibling output directories.
- 2026-08-14: Implemented checkpoint 3.2 in `7a921fb`; validated provider results publish atomically only after output/manifest checks, exact repeats avoid provider calls, and manifests/results expose cache outcomes.
- 2026-08-14: Review PASS for checkpoint 3.2 after 190-test regression evidence and cross-instance atomicity, corruption repair, invalid-result publication, grouping, stitching, and selective-invalidation probes; auto-advanced to checkpoint 3.3.
- 2026-08-14: Began checkpoint 3.3 by inventorying all error/warning codes, phase coverage, secret surfaces, untrusted YAML/cache/path inputs, and output publication/cancellation boundaries.
- 2026-08-14: Implemented checkpoint 3.3 in `b41873a` with a stable diagnostic registry, phase/code/correction CLI output, bounded safe YAML structures, atomic exclusive publication, cancellation cleanup, adversarial tests, and troubleshooting guidance.
- 2026-08-14: Review FAIL: corrupt non-empty provider audio emits `DECODE_ERROR` without the available provider request, scene, speaker, or segment attribution required for operational diagnosis.
- 2026-08-14: Resolved ISSUE-303 in `54d9d8a`; file and dialogue-stream failures now retain safe provider/request/scene/segment/character attribution through lower-level decode and assembly errors.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- Stage 2 rollup: 171 tests plus Ruff and strict `mypy src` passed; `signal_below` produced 30 decodable segment files and a manifest.
- `0b831cf` — structured sync/async streaming implementation and acceptance tests.
- `.venv/bin/python -m pytest -q` — 178 passed; Ruff and strict `mypy src` passed.
- Comprehensive trace — 36 ordered chunks: 30 attributed audio chunks and 6 pause/marker/note events.
- `ed77a8d` — streaming transport reads only on demand and closes its underlying response; direct transport tests verify first read before EOF and bounded provider lookahead.
- `.venv/bin/python -m pytest -q` — 180 passed after transport hardening.
- Checkpoint 3.1 review: 26 focused streaming/provider/source-form tests passed; `57eca2f` adds the final HTTP failure/cleanup probe.
- `7a921fb` — content-addressed request/segment identities, validated atomic records, cache-aware rendering, and incremental-regeneration coverage.
- `.venv/bin/python -m pytest tests/test_cache.py -q` — 8 passed; incremental integration probe passed with call counts 4 initial + 3 continuity-dependent misses.
- `.venv/bin/python -m pytest -q` — 190 passed; Ruff and strict `mypy src` passed.
- Checkpoint 3.2 review: 8 cache tests and the incremental integration probe passed; `8f364ed` verifies separate cache instances under concurrent replacement.
- `b41873a` — diagnostic/security/failure-recovery implementation; pushed to `origin/main`.
- `.venv/bin/python -m pytest tests/test_security.py tests/test_failures.py tests/test_cli.py -q` — 23 passed.
- `.venv/bin/python -m pytest -q` — 202 passed; Ruff and strict `mypy src` passed.
- Adversarial corrupt-audio probe — `DecodeError DECODE_ERROR audio_assembly {'output_format': 'wav_16000'}`; request/segment/provider context is missing.
- `54d9d8a` — request-aware diagnostic enrichment for file generation, assembly, output writing, and streaming; pushed to `origin/main`.
- `.venv/bin/python -m pytest tests/test_failures.py tests/test_security.py tests/test_streaming.py -q` — 26 passed; corrupt file/stream audio assertions include full safe attribution.
- `.venv/bin/python -m pytest -q` — 204 passed; Ruff and strict `mypy src` passed.
- Next: repeat checkpoint 3.3 adversarial review.

## Workflow state
<!-- Dispatcher flags. Checked = active/needed. Cleared by the loop that handles each flag. -->
- [x] RUN_CONTEXT_CAPTURE
- [ ] STAGE_DESIGNED
- [ ] MAINTENANCE_CYCLE_DONE
- [ ] RETROSPECTIVE_DONE
- [x] PROCESS_IMPROVEMENTS_DONE

## Active issues
<!-- Keep only active issues here. Move resolved items to HISTORY.md. -->

- None.

## Decisions
<!-- Only decisions that matter for future work. -->

- 2026-08-14: Treat `DESIGN.md` as the ELScript 1.0 behavior contract and `README.md` as the target operator experience.
- 2026-08-14: Keep deterministic fake-provider acceptance mandatory; defer paid credentialed ElevenLabs smoke tests until credentials and charge approval are available.
- 2026-08-14: Work directly on the current `main` branch and commit/push completed units, per operator instruction.
- 2026-08-14: Auto streaming uses independently attributable speech requests; explicit dialogue streams buffer one provider request for timestamp-based segment attribution, while HTTP response consumption remains incremental and closeable.
- 2026-08-14: File renders share a local content cache at `<output-parent>/.cache/elscript`; streaming stays write-free, and cache keys exclude logical/output identity while including material provider and continuity inputs.
