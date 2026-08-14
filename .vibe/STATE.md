# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 2
- Checkpoint: 2.2
- Status: IN_REVIEW  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Convert resolved semantic intent into validated ElevenLabs text, tags, pronunciation, and endpoint options without silent loss.

## Deliverables (current checkpoint)

- `src/elscript/providers/elevenlabs_prompt.py` for versioned semantic-to-provider translation.
- Exact, boundary-safe pronunciation term substitution and dictionary locator handling.
- Scoped raw `api` option resolution and model/endpoint validation.
- Translation and warning tests in `tests/test_elevenlabs_prompt.py`.

## Acceptance (current checkpoint)

- [x] Eleven v3 emotion, intensity, energy, pace, volume, delivery, cues, and authored tags preserve deterministic authored order.
- [x] Exact/case-sensitive pronunciation matching avoids substring corruption and v3 IPA compiles to native form.
- [x] Dictionary limits and raw provider settings are validated for the selected endpoint/model before generation.
- [x] Unsupported semantic intent yields a stable warning or capability error, never silent omission.
- [x] Translation version and all material provider inputs are available to render identity.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 1 into `.vibe/HISTORY.md`; the canonical load-to-compile front half passes 68 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 2.1 for provider capability contracts and deterministic render planning; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Implemented endpoint-specific provider contracts, deterministic request grouping/splitting, pre-generation capability failures, ordered plan events, and a no-network deterministic fake provider for checkpoint 2.1.
- 2026-08-14: Review PASS for checkpoint 2.1 after applying scene-level chunk ceilings and correcting fake-provider audio identity to include semantic performance but exclude editorial IDs; 87 tests and static gates pass, and the pointer advanced to 2.2.
- 2026-08-14: Implemented versioned Eleven v3 semantic/audio-tag translation, boundary-safe pronunciation and native IPA, endpoint-scoped raw-option validation, provider request materialization, and pre-split prepared-text planning for checkpoint 2.2.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- `.venv/bin/python -m pytest tests/test_elevenlabs_prompt.py tests/test_pronunciation.py tests/test_planner.py tests/test_capabilities.py -q` -> 46 passed.
- `.venv/bin/python -m pytest -q`, Ruff, and strict mypy -> 114 passed; static checks pass.
- path: src/elscript/providers/elevenlabs_prompt.py

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
