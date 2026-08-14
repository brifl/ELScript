# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 2
- Checkpoint: 2.1
- Status: NOT_STARTED  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Turn compiled timelines into deterministic provider requests without conflating authored segments, request groups, or output boundaries.

## Deliverables (current checkpoint)

- `src/elscript/providers/base.py` defining provider, capability, generation, metadata, and streaming contracts.
- `src/elscript/planner.py` implementing `auto`, `speech`, and `dialogue` strategies plus grouping and split rules.
- A deterministic fake provider used by integration tests without network or charges.
- Planner/capability tests in `tests/test_planner.py`.

## Acceptance (current checkpoint)

- [ ] Planning honors scene boundaries, explicit pauses, model/settings/dictionary compatibility, output mode, and streaming mode.
- [ ] Dialogue groups never exceed configured/provider character or unique-voice limits and preserve speaker/segment identity.
- [ ] A logical segment split for provider limits retains ordered subparts under one logical ID.
- [ ] Unsupported requested capabilities fail before generation unless an explicit coded degradation policy applies.
- [ ] Identical inputs produce structurally identical plans.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 1 into `.vibe/HISTORY.md`; the canonical load-to-compile front half passes 68 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 2.1 for provider capability contracts and deterministic render planning; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- `python3 .codex/skills/vibe-loop/scripts/agentctl.py --repo-root . validate --format json` -> valid at Stage 2 / checkpoint 2.1.
- path: .vibe/HISTORY.md

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
