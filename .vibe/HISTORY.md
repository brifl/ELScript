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
- 2026-08-14 — Stage 2: ElevenLabs rendering and file outputs
  - Shipped provider-neutral capability/request contracts, deterministic planning, a no-network fake provider, versioned ElevenLabs semantic/pronunciation translation, and an injectable production HTTP adapter.
  - Added real codec-backed audio assembly, all three safe output modes, privacy-aware global-timeline manifests, and one canonical file/YAML/mapping/directory render pipeline behind the Python API and thin CLI.
  - Review hardening covered chunk and continuity boundaries, malformed provider timing, zero-retention constraints, path containment and preflight, rollback after partial failure, request-spanning alignment, recursive secret removal, and the public ElevenLabs branch without a live call.
  - Evidence: commits `9d14a09` through `9dcf402`; 171 tests, Ruff, strict mypy, and the 30-segment `signal_below` CLI demo passed at consolidation.

## Resolved issues

- ISSUE-305 — Selected `elscript-audio` as the owned public distribution identity while
  retaining the `elscript` Python package and command; metadata, docs, artifact checks,
  and CI were synchronized in `71f3627`. Publication remains explicitly deferred.
- ISSUE-306 — Separate cache instances could observe transient misses/corruption during
  concurrent replacement on a Windows-mounted workspace. `ce8d02d` shares locks per
  cache root; the contention test passed 10 consecutive runs and the full suite passed.

## Process notes

- 2026-08-14: Stage consolidation keeps acceptance detail in git history while preserving the next executable stage in PLAN and current truth in STATE.
