# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 1
- Checkpoint: 1.3
- Status: IN_REVIEW  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Reject invalid or ambiguous ELScript documents before compilation with actionable paths and stable diagnostic codes.

## Deliverables (current checkpoint)

- `src/elscript/schema.py` for top-level, render, pronunciation, preset, character, scene, entry, and export validation.
- `src/elscript/validation.py` for version, character, preset, ID, range, and cross-reference checks.
- Valid and invalid contract fixtures derived from the complete `DESIGN.md` example.
- Schema and reference tests in `tests/test_schema.py` and `tests/test_validation.py`.

## Acceptance (current checkpoint)

- [x] The comprehensive example validates, including scalar speech, structured `say`, `set`, `with`, `reset`, `cue`, `tags`, `pause`, `note`, and `marker` forms.
- [x] Unknown core fields, unsupported schema versions, malformed values, and performance values outside defined ranges fail before rendering.
- [x] Unknown characters/presets, duplicate logical IDs, and missing required voice IDs produce actionable source/YAML paths.
- [x] The `api` escape hatch preserves structured provider data without accepting credentials or weakening core schema checks.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Replaced the placeholder roadmap with three implementation stages derived from `DESIGN.md` and aligned the active pointer to checkpoint 1.1.
- 2026-08-14: Implemented Python 3.11+ packaging, immutable boundary models, the documented error hierarchy, public API signatures, CLI help, and contract tests; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Review PASS for checkpoint 1.1; verified the built wheel in a fresh environment, reran tests/lint/types, probed source ambiguity and nested redaction, and auto-advanced to 1.2.
- 2026-08-14: Implemented safe YAML/file/directory/mapping loading, provenance, deterministic discovery/order, section-aware merging, conflict diagnostics, and split-project fixtures for checkpoint 1.2.
- 2026-08-14: Review PASS for checkpoint 1.2 after fixing appended-list provenance, rerunning the full suite/static checks, and rejecting an external-source symlink probe; auto-advanced to 1.3.
- 2026-08-14: Implemented strict ELScript 1.0 structural models, source-aware schema diagnostics, credential checks, and character/preset/ID reference validation for checkpoint 1.3.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- `.venv/bin/python -m pytest tests/test_schema.py tests/test_validation.py tests/test_design_examples.py -q` -> 10 passed.
- `.venv/bin/python -m pytest -q`, Ruff, and strict mypy -> 38 passed; static checks pass.
- path: tests/test_design_examples.py

## Workflow state
<!-- Dispatcher flags. Checked = active/needed. Cleared by the loop that handles each flag. -->
- [ ] RUN_CONTEXT_CAPTURE
- [x] STAGE_DESIGNED
- [x] MAINTENANCE_CYCLE_DONE
- [x] RETROSPECTIVE_DONE
- [x] PROCESS_IMPROVEMENTS_DONE

## Active issues
<!-- Keep only active issues here. Move resolved items to HISTORY.md. -->

- None.

## Decisions
<!-- Only decisions that matter for future work. -->

- 2026-08-14: Treat `DESIGN.md` as the ELScript 1.0 behavior contract and `README.md` as the target operator experience.
- 2026-08-14: Keep deterministic fake-provider acceptance mandatory; defer paid credentialed ElevenLabs smoke tests until credentials and charge approval are available.
- 2026-08-14: Work directly on the current `main` branch and commit/push completed units, per operator instruction.
