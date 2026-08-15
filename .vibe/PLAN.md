# PLAN

## Execution frame

- Goal: Ship ELScript 1.0 as a trustworthy Python library and CLI that turns one file, a project directory, YAML text, or a Python mapping into expressive ElevenLabs audio, structured streaming chunks, and a safe machine-readable manifest.
- Context: `DESIGN.md` is the behavior contract and `README.md` is the intended operator experience; Stages 1–3 established the tested authoring, rendering, streaming, caching, diagnostics, and local distribution baseline.
- Constraints:
  - Keep one canonical load -> merge -> validate -> configure -> compile -> plan -> generate -> output pipeline for every entry point.
  - Preserve semantic authoring independently from provider request mechanics; unsupported intent must fail or produce an explicit coded warning.
  - Treat credentials, YAML, cache records, and output paths as security boundaries.
  - Keep the CLI a thin file-rendering wrapper; streaming remains Python-only.
- Done when: supported current CPython versions pass the full cross-platform CI and artifact-install matrix, while publication and credentialed provider calls remain separately authorized operations.

## Architecture decisions

- Use a `src/elscript` Python package with explicit domain models between pipeline phases so source, provider, and output concerns do not leak across boundaries.
- Make parsing, merge, schema/reference validation, configuration resolution, compilation, and request planning pure or side-effect-free; isolate network, cache, and filesystem writes behind adapters.
- Model authored speech segments, provider requests, and output files as separate identities because their boundaries intentionally differ.
- Use a deterministic fake provider for required end-to-end acceptance; keep paid credentialed ElevenLabs calls opt-in.
- Build one synchronous core pipeline and adapt it deliberately for `stream()` and `astream()` so API and CLI behavior cannot drift.
- Test each declared current CPython minor on all three hosted operating systems; keep action runtimes current and the workflow read-only rather than adding release automation.

## Completed baseline

- Stages 1–3 delivered the ELScript 1.0 language, canonical rendering pipeline,
  ElevenLabs/fake adapters, file and streaming outputs, cache, diagnostics, public docs,
  and locally verified `elscript-audio` artifacts. Rollups live in `.vibe/HISTORY.md` and
  checkpoint evidence remains in git history.

## Stage 4 — Current runtime and CI compatibility

Milestone: The supported Python contract is exercised on current interpreters and hosted
operating systems without deprecated CI runtimes or accidental release authority.

### 4.1 — Modernize the supported Python and GitHub Actions matrix

- Objective:
  - Prove the existing public package on CPython 3.11–3.14 across Linux, macOS, and Windows using current Node 24-based GitHub actions.
- Deliverables:
  - `.github/workflows/ci.yml` updated to current action majors and CPython 3.11–3.14.
  - `pyproject.toml` classifiers and public support wording synchronized with the tested matrix.
  - Focused metadata/workflow assertions that keep distribution identity and release permissions stable.
  - Remote CI evidence for every OS/interpreter combination and the artifact-install job.
- Acceptance:
  - [ ] CI runs the full suite on CPython 3.11, 3.12, 3.13, and 3.14 on Linux, macOS, and Windows.
  - [ ] Checkout, Python setup, and artifact upload use supported Node 24-based action majors with no Node 20 deprecation annotations.
  - [ ] The build job creates, checks, installs, imports, and invokes the `elscript-audio` wheel on Python 3.14.
  - [ ] Project metadata names every tested Python minor without changing the `elscript` import or CLI command.
  - [ ] The workflow retains read-only contents permission and contains no package-index upload, tag, release, credential, or paid-provider step.
  - [ ] Local full-suite, Ruff, strict mypy, build, Twine, and distribution-content checks remain green.
- Demo commands:
  - `python -m pytest -q`
  - `python -m ruff check src tests tools/check_dist.py && python -m mypy src`
  - `python -m build && python -m twine check dist/* && python tools/check_dist.py dist`
- Evidence:
  - One successful CI run URL showing all 13 jobs and no Node 20 annotations.
  - Local test/static/build summary plus verified artifact names.

## Non-blocking verification backlog

- [DEFERRED] Publish `elscript-audio` to PyPI; owner: human-assisted agent; revisit only
  after a new explicit operator instruction authorizes the upload and release/tag actions.
- [DEFERRED] Run a minimal real ElevenLabs speech/timestamp/dialogue smoke before the first release; owner: human-assisted agent; revisit when `ELEVENLABS_API_KEY` and approval to incur a small provider charge are available.
- Re-check current ElevenLabs model, endpoint, output-format, retention, and account-limit assumptions before release; update only the provider capability layer when upstream behavior has changed.
