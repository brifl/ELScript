# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 2
- Checkpoint: 2.4
- Status: IN_REVIEW  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Materialize valid `single`, `scene`, and `segment` audio outputs with deterministic timing, silence insertion, and path containment.

## Deliverables (current checkpoint)

- `src/elscript/audio.py` for decode, concatenation, explicit silence, format handling, and optional normalization.
- `src/elscript/output.py` for naming, sanitization, collision detection, containment, directories, and overwrite policy.
- Small deterministic audio fixtures and tests in `tests/test_audio.py` and `tests/test_output.py`.

## Acceptance (current checkpoint)

- [ ] Single and scene modes preserve authored order and insert explicit pauses within encoding tolerance.
- [ ] Segment mode emits one valid file per audible speech segment and no standalone pause files.
- [ ] Filenames use the documented script/scene/global ordinal/logical speaker rules and remain lexically sortable above 9,999 segments.
- [ ] Malicious or colliding IDs cannot escape `output_dir`, and the default overwrite policy refuses unrelated existing files.
- [ ] Output format/extension and optional loudness normalization are deterministic and reported as effective settings.

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

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- `.venv/bin/python -m pytest tests/test_audio.py tests/test_output.py -q` -> 16 passed.
- `.venv/bin/python -m pytest -q`, Ruff, and strict mypy -> 146 passed; static checks pass.
- `tests/test_security.py -k output_path -q` -> 1 passed.
- path: src/elscript/audio.py
- commit: `606c0d6` (`2.4: Assemble and write safe audio outputs`), pushed to `origin/main`.

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
