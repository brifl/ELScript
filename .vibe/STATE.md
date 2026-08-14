# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 2
- Checkpoint: 2.3
- Status: IN_REVIEW  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Execute planned speech/dialogue requests through ElevenLabs normal and timestamp endpoints with stable result and error translation.

## Deliverables (current checkpoint)

- `src/elscript/providers/elevenlabs.py` implementing capability description, request execution, and metadata extraction.
- Transport boundary supporting deterministic mocked HTTP/SDK contract tests.
- Continuity support for context text and request stitching where compatible.
- Adapter tests in `tests/test_elevenlabs_provider.py` with recorded request/response shapes and no live calls.

## Acceptance (current checkpoint)

- [ ] Speech and dialogue plans select the correct normal or timestamp operation and send every validated material option.
- [ ] Audio bytes, request IDs, character alignment, normalized alignment, and voice segments are normalized into provider-neutral results.
- [ ] Authentication, rate-limit, capability/account, and generation failures map to stable ELScript error categories with secrets redacted.
- [ ] Continuity data is bounded to provider limits and disabled when incompatible with zero-retention behavior.
- [ ] The automated suite performs no network calls and cannot incur provider charges.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 1 into `.vibe/HISTORY.md`; the canonical load-to-compile front half passes 68 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 2.1 for provider capability contracts and deterministic render planning; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Implemented endpoint-specific provider contracts, deterministic request grouping/splitting, pre-generation capability failures, ordered plan events, and a no-network deterministic fake provider for checkpoint 2.1.
- 2026-08-14: Review PASS for checkpoint 2.1 after applying scene-level chunk ceilings and correcting fake-provider audio identity to include semantic performance but exclude editorial IDs; 87 tests and static gates pass, and the pointer advanced to 2.2.
- 2026-08-14: Implemented versioned Eleven v3 semantic/audio-tag translation, boundary-safe pronunciation and native IPA, endpoint-scoped raw-option validation, provider request materialization, and pre-split prepared-text planning for checkpoint 2.2.
- 2026-08-14: Review PASS for checkpoint 2.2 after adversarial checks for pre-split pronunciation, repeated expressive prefixes, indivisible IPA, endpoint option fallbacks, stable warnings, and secret-safe material identity; pointer advanced to 2.3.
- 2026-08-14: Implemented the injectable ElevenLabs HTTP adapter, create/stream route selection, timestamp and dialogue metadata normalization, secret-safe failure mapping, and zero-retention-aware continuity validation for checkpoint 2.3.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- `.venv/bin/python -m pytest tests/test_elevenlabs_provider.py tests/test_elevenlabs_prompt.py -q` -> 35 passed.
- `.venv/bin/python -m pytest -q`, Ruff, and strict mypy -> 128 passed; static checks pass.
- path: src/elscript/providers/elevenlabs.py
- commit: `3cca706` (`2.3: Implement ElevenLabs generation adapter`), pushed to `origin/main`.

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
