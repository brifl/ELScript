# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 3
- Checkpoint: 3.1
- Status: IN_PROGRESS  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Stream ordered, attributed audio and timeline events with natural backpressure and cancellation-safe async behavior.

## Deliverables (current checkpoint)

- `stream()` and `astream()` implementations in `src/elscript/api.py` over the canonical front half of the pipeline.
- Provider streaming support and event normalization in the provider contracts/adapters.
- Streaming state/order/backpressure/cancellation tests in `tests/test_streaming.py`.

## Acceptance (current checkpoint)

- [ ] Streaming accepts every source form and the same effective configuration as file rendering without requiring `output_dir`.
- [ ] Consumers can identify scene, logical segment, ordinal, speaker, format, and final-segment boundaries for every audio chunk.
- [ ] Pauses and markers are preserved consistently as documented ordered events or silence chunks.
- [ ] Sync iteration applies consumer backpressure and async cancellation closes the active request without corrupting a later render.
- [ ] Streaming writes no files unless a future explicit tee feature is separately requested.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 2 into `.vibe/HISTORY.md`; the canonical source-to-audio/manifest pipeline passes 171 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 3.1 for structured synchronous and asynchronous streaming; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Began the canonical sync/async stream implementation with typed provider metadata, ordered timeline events, demand-driven iteration, and explicit dialogue attribution.
- 2026-08-14: Implemented checkpoint 3.1 in `0b831cf`; auto-mode streams independently attributable speech requests, explicit dialogue is split using provider voice timing, and async iteration closes active work on cancellation.
- 2026-08-14: Review FAIL: the urllib production transport buffers `response.read()` before provider iteration, so real ElevenLabs calls do not yet provide network-level streaming or close propagation.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- Stage 2 rollup: 171 tests plus Ruff and strict `mypy src` passed; `signal_below` produced 30 decodable segment files and a manifest.
- `0b831cf` — structured sync/async streaming implementation and acceptance tests.
- `.venv/bin/python -m pytest -q` — 178 passed; Ruff and strict `mypy src` passed.
- Comprehensive trace — 36 ordered chunks: 30 attributed audio chunks and 6 pause/marker/note events.
- Review finding: `UrllibElevenLabsTransport.send()` reads the complete body before `ElevenLabsProvider.stream()` can yield; focused fake-provider backpressure tests cannot verify the production network path.

## Workflow state
<!-- Dispatcher flags. Checked = active/needed. Cleared by the loop that handles each flag. -->
- [x] RUN_CONTEXT_CAPTURE
- [ ] STAGE_DESIGNED
- [ ] MAINTENANCE_CYCLE_DONE
- [ ] RETROSPECTIVE_DONE
- [x] PROCESS_IMPROVEMENTS_DONE

## Active issues
<!-- Keep only active issues here. Move resolved items to HISTORY.md. -->

- [ ] ISSUE-301: Production transport buffers streaming responses
  - Impact: MAJOR
  - Status: IN_PROGRESS
  - Owner: agent
  - Unblock Condition: Streaming operations consume an incrementally readable transport response and closing/cancelling the public iterator closes that response.
  - Evidence Needed: Transport-level tests prove first-chunk delivery before EOF, bounded read-ahead, and close propagation; checkpoint streaming tests and full suite pass.
  - Notes: Non-streaming requests should retain their existing buffered response path and error translation.

## Decisions
<!-- Only decisions that matter for future work. -->

- 2026-08-14: Treat `DESIGN.md` as the ELScript 1.0 behavior contract and `README.md` as the target operator experience.
- 2026-08-14: Keep deterministic fake-provider acceptance mandatory; defer paid credentialed ElevenLabs smoke tests until credentials and charge approval are available.
- 2026-08-14: Work directly on the current `main` branch and commit/push completed units, per operator instruction.
