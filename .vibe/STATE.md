# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 3
- Checkpoint: 3.2
- Status: NOT_STARTED  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Reuse provider results only when every material audio input and continuity dependency matches.

## Deliverables (current checkpoint)

- `src/elscript/cache.py` for canonical fingerprints, atomic cache records, validation, and lookup.
- Request-context dependency tracking for grouping, neighbors, and stitching invalidation.
- Cache observability in render results and manifests.
- Cache hit/miss/corruption/invalidation tests in `tests/test_cache.py`.

## Acceptance (current checkpoint)

- [ ] Fingerprints include the design-mandated provider, prompt, settings, semantic translation, pronunciation, seed, language, normalization, context, and adapter versions.
- [ ] Fingerprints exclude credentials, output directories/names, and unrelated metadata.
- [ ] Exact repeats avoid provider calls and expose cache hits without changing output semantics.
- [ ] Segment or grouping changes invalidate every continuity-dependent request while preserving unrelated reusable requests.
- [ ] Corrupt/incomplete entries are ignored safely and writes are atomic under concurrent readers.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 2 into `.vibe/HISTORY.md`; the canonical source-to-audio/manifest pipeline passes 171 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 3.1 for structured synchronous and asynchronous streaming; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Began the canonical sync/async stream implementation with typed provider metadata, ordered timeline events, demand-driven iteration, and explicit dialogue attribution.
- 2026-08-14: Implemented checkpoint 3.1 in `0b831cf`; auto-mode streams independently attributable speech requests, explicit dialogue is split using provider voice timing, and async iteration closes active work on cancellation.
- 2026-08-14: Review FAIL: the urllib production transport buffers `response.read()` before provider iteration, so real ElevenLabs calls do not yet provide network-level streaming or close propagation.
- 2026-08-14: Resolved ISSUE-301 in `ed77a8d` with incremental urllib reads, arbitrary-boundary timestamp JSON decoding, one-chunk final lookahead, and socket-close propagation.
- 2026-08-14: Review PASS for checkpoint 3.1 after 180-test regression evidence and targeted production transport, close, cancellation, malformed-data, and redaction probes; auto-advanced to checkpoint 3.2.

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
- Next: `.venv/bin/python -m pytest tests/test_cache.py -q` for checkpoint 3.2.

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
