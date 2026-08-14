# HISTORY

## Rules

- This file is **non-authoritative**.
- Use it for rollups, resolved issues, and consolidation notes.
- Prefer links/identifiers rather than copying large blocks.

## Completed stages

- 2026-08-14 — Stage 1: Deterministic authoring and compilation core
  - Shipped the Python package/public contracts and a canonical, source-aware load and merge pipeline for files, directories, YAML text, and mappings.
  - Added strict ELScript 1.0 schema/reference validation, layered secret-safe configuration, and deterministic compilation of sticky character state into speech and ordered non-speech timeline events.
  - Review hardening covered safe YAML 1.2 scalar handling, symlink containment, credential redaction, falsey configuration values, structured-speech directions, semantic/provider state isolation, and stable IDs.
  - Evidence: commits `bab4d35` through `52d9290`; 68 tests, Ruff, and strict mypy passed at consolidation.

## Resolved issues

- None recorded.

## Process notes

- 2026-08-14: Stage consolidation keeps acceptance detail in git history while preserving the next executable stage in PLAN and current truth in STATE.
