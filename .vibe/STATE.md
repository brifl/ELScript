# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 2
- Checkpoint: 2.6
- Status: IN_REVIEW  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Deliver the README render experience through one end-to-end pipeline for every source form and all file output modes.

## Deliverables (current checkpoint)

- `src/elscript/api.py` implementing `render`, `render_yaml`, and `render_document` through the canonical pipeline.
- `src/elscript/cli.py` file-render command with documented overrides, exit codes, warnings, and concise diagnostics.
- End-to-end fake-provider fixtures for the comprehensive single-file and split-project examples.
- Integration and CLI tests in `tests/test_render_integration.py` and `tests/test_cli.py`.

## Acceptance (current checkpoint)

- [ ] File, directory, YAML-text, mapping, convenience functions, and CLI calls share identical compiled plans and output semantics.
- [ ] The comprehensive example renders valid single, scene, and segment assets plus manifests using the fake provider.
- [ ] CLI overrides obey configuration precedence and errors exit nonzero with phase, source/path context, and an actionable correction.
- [ ] `RenderResult` exposes paths, duration, scenes, segments, provider-request count, and warnings without requiring manifest parsing.
- [ ] CLI has no alternate parser/compiler/provider path and exposes no streaming switch.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 1 into `.vibe/HISTORY.md`; the canonical load-to-compile front half passes 68 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 2.1 for provider capability contracts and deterministic render planning; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Implemented endpoint-specific provider contracts, deterministic request grouping/splitting, pre-generation capability failures, ordered plan events, and a no-network deterministic fake provider for checkpoint 2.1.
- 2026-08-14: Review PASS for checkpoint 2.1 after applying scene-level chunk ceilings and correcting fake-provider audio identity to include semantic performance but exclude editorial IDs; 87 tests and static gates pass, and the pointer advanced to 2.2.
- 2026-08-14: Implemented versioned Eleven v3 semantic/audio-tag translation, boundary-safe pronunciation and native IPA, endpoint-scoped raw-option validation, provider request materialization, and pre-split prepared-text planning for checkpoint 2.2.
- 2026-08-14: Review PASS for checkpoint 2.2 after adversarial checks for pre-split pronunciation, repeated expressive prefixes, indivisible IPA, endpoint option fallbacks, stable warnings, and secret-safe material identity; pointer advanced to 2.3.
- 2026-08-14: Implemented the injectable ElevenLabs HTTP adapter, create/stream route selection, timestamp and dialogue metadata normalization, secret-safe failure mapping, and zero-retention-aware continuity validation for checkpoint 2.3.
- 2026-08-14: Review PASS for checkpoint 2.3 after removing an output-format-specific Accept header and adding malformed-timing and transport-failure probes; pointer advanced to 2.4.
- 2026-08-14: Implemented real codec-backed audio decoding/encoding, deterministic silence and RMS normalization, three-mode output assembly, safe sortable naming, dialogue segment extraction, and exclusive file creation for checkpoint 2.4; upgraded the fake provider to emit valid deterministic audio.
- 2026-08-14: Review PASS for checkpoint 2.4 after a real default-MP3 fake-provider segment demo and explicit rejection of filename-shaped output directories; pointer advanced to 2.5.
- 2026-08-14: Implemented versioned privacy-aware manifests for every file mode, global/file-relative timeline translation, alignment and dialogue attribution, configurable metadata retention, credential-value scrubbing, and exclusive manifest writes for checkpoint 2.5.
- 2026-08-14: Review PASS for checkpoint 2.5 after verifying cumulative alignment offsets for a logical segment split across three requests and rejecting dialogue metadata that reverses authored input order; pointer advanced to 2.6.
- 2026-08-14: Implemented the canonical file-render pipeline and thin CLI, provider selection and warning collection, pre-generation destination checks, partial-output rollback, structured `RenderResult` mapping, and equivalent comprehensive single/split fixtures for checkpoint 2.6.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- `.venv/bin/python -m pytest tests/test_render_integration.py tests/test_cli.py -q` -> 13 passed; four source forms, three output modes, result contracts, CLI overrides/errors, preflight, and rollback covered.
- `.venv/bin/elscript tests/fixtures/signal_below --output build/demo-audio --mode segment` -> 30 decodable WAV assets plus `signal-below.manifest.json`.
- full suite -> 170 passed; Ruff and strict `mypy src` pass; commit `cbe0ef7` pushed to `origin/main`.

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
