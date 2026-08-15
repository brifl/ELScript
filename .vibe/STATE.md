# STATE

## Session read order

1) `AGENTS.md` (optional if already read this session)
2) `.vibe/STATE.md` (this file)
3) `.vibe/PLAN.md`
4) `.vibe/HISTORY.md` (optional)

## Current focus

- Stage: 4
- Checkpoint: 4.1
- Status: IN_REVIEW  <!-- one of: NOT_STARTED | IN_PROGRESS | IN_REVIEW | BLOCKED | DONE -->

## Objective (current checkpoint)

- Prove the existing public package on CPython 3.11–3.14 across Linux, macOS, and Windows using current Node 24-based GitHub actions.

## Deliverables (current checkpoint)

- `.github/workflows/ci.yml` updated to current action majors and CPython 3.11–3.14.
- `pyproject.toml` classifiers and public support wording synchronized with the tested matrix.
- Focused metadata/workflow assertions that keep distribution identity and release permissions stable.
- Remote CI evidence for every OS/interpreter combination and the artifact-install job.

## Acceptance (current checkpoint)

- [ ] CI runs the full suite on CPython 3.11, 3.12, 3.13, and 3.14 on Linux, macOS, and Windows.
- [ ] Checkout, Python setup, and artifact upload use supported Node 24-based action majors with no Node 20 deprecation annotations.
- [ ] The build job creates, checks, installs, imports, and invokes the `elscript-audio` wheel on Python 3.14.
- [ ] Project metadata names every tested Python minor without changing the `elscript` import or CLI command.
- [ ] The workflow retains read-only contents permission and contains no package-index upload, tag, release, credential, or paid-provider step.
- [ ] Local full-suite, Ruff, strict mypy, build, Twine, and distribution-content checks remain green.

## Work log (current session)
<!-- Append-only bullets for what changed and why. Prefer file/line references. -->

- 2026-08-14: Consolidated completed Stage 2 into `.vibe/HISTORY.md`; the canonical source-to-audio/manifest pipeline passes 171 tests plus Ruff and strict mypy.
- 2026-08-14: Advanced to checkpoint 3.1 for structured synchronous and asynchronous streaming; preserved unrelated pre-existing line-ending changes in `.gitignore`, `AGENTS.md`, and `DESIGN.md`.
- 2026-08-14: Began the canonical sync/async stream implementation with typed provider metadata, ordered timeline events, demand-driven iteration, and explicit dialogue attribution.
- 2026-08-14: Implemented checkpoint 3.1 in `0b831cf`; auto-mode streams independently attributable speech requests, explicit dialogue is split using provider voice timing, and async iteration closes active work on cancellation.
- 2026-08-14: Review FAIL: the urllib production transport buffers `response.read()` before provider iteration, so real ElevenLabs calls do not yet provide network-level streaming or close propagation.
- 2026-08-14: Resolved ISSUE-301 in `ed77a8d` with incremental urllib reads, arbitrary-boundary timestamp JSON decoding, one-chunk final lookahead, and socket-close propagation.
- 2026-08-14: Review PASS for checkpoint 3.1 after 180-test regression evidence and targeted production transport, close, cancellation, malformed-data, and redaction probes; auto-advanced to checkpoint 3.2.
- 2026-08-14: Began checkpoint 3.2 with request-granular content identity, conservative immediate-neighbor continuity dependencies, and a local atomic cache shared by sibling output directories.
- 2026-08-14: Implemented checkpoint 3.2 in `7a921fb`; validated provider results publish atomically only after output/manifest checks, exact repeats avoid provider calls, and manifests/results expose cache outcomes.
- 2026-08-14: Review PASS for checkpoint 3.2 after 190-test regression evidence and cross-instance atomicity, corruption repair, invalid-result publication, grouping, stitching, and selective-invalidation probes; auto-advanced to checkpoint 3.3.
- 2026-08-14: Began checkpoint 3.3 by inventorying all error/warning codes, phase coverage, secret surfaces, untrusted YAML/cache/path inputs, and output publication/cancellation boundaries.
- 2026-08-14: Implemented checkpoint 3.3 in `b41873a` with a stable diagnostic registry, phase/code/correction CLI output, bounded safe YAML structures, atomic exclusive publication, cancellation cleanup, adversarial tests, and troubleshooting guidance.
- 2026-08-14: Review FAIL: corrupt non-empty provider audio emits `DECODE_ERROR` without the available provider request, scene, speaker, or segment attribution required for operational diagnosis.
- 2026-08-14: Resolved ISSUE-303 in `54d9d8a`; file and dialogue-stream failures now retain safe provider/request/scene/segment/character attribution through lower-level decode and assembly errors.
- 2026-08-14: Re-review FAIL: unlike file generation, an unexpected streaming-adapter exception escapes as raw `RuntimeError` with its potentially secret-bearing message.
- 2026-08-14: Resolved ISSUE-304 in `8723b92`; streaming now normalizes ordinary adapter failures to attributed, secret-safe `GENERATION_ERROR` while preserving cancellation semantics.
- 2026-08-14: Review PASS for checkpoint 3.3 after 27 focused diagnostic/security/CLI tests, 206 full-suite tests, strict workflow validation, and adversarial file/stream failure probes; auto-advanced to checkpoint 3.4.
- 2026-08-14: Began checkpoint 3.4 by auditing README examples, distribution contents, build isolation, public metadata, documentation gaps, and cross-platform CI/release checks.
- 2026-08-14: Implemented checkpoint 3.4 in `7a5662e`; public examples/reference docs, scoped package metadata, artifact verification, changelog/release guidance, and Linux/macOS/Windows CI now form one executable release surface.
- 2026-08-14: Review FAIL/BLOCKED: the `elscript` distribution name is already owned on PyPI by an unrelated Eliot programming-language project, so the documented install command and publication target require an operator naming/ownership decision.
- 2026-08-14: Operator selected `elscript-audio` as the distribution name and explicitly deferred publication; the import package and CLI remain `elscript`.
- 2026-08-14: Resolved ISSUE-305 in `71f3627` with synchronized metadata, install guidance, artifact checks, CI naming, and a publication deferral.
- 2026-08-14: Full-suite verification exposed a reproducible cross-instance cache replacement race on the Windows-mounted workspace; resolved ISSUE-306 in `ce8d02d` with one shared in-process lock per cache root.
- 2026-08-14: Review PASS for checkpoint 3.4; package identity, docs, artifacts, isolated installation, deterministic examples, cache concurrency, and publication boundaries satisfy the release-readiness contract. The active plan is exhausted.
- 2026-08-14: Designed Stage 4 from repository and live CI evidence: the six-job Python 3.11/3.12 matrix passes, but every job warns about deprecated Node 20 action runtimes and Python 3.13/3.14 are not exercised despite the open-ended `>=3.11` requirement.
- 2026-08-14: Implemented checkpoint 4.1 in `afec37c`; CI now exercises CPython 3.11–3.14 on all three hosted operating systems with Node 24 actions, Python 3.14 artifact installation, synchronized classifiers, and an explicit no-release-authority assertion.

## Evidence
<!-- Paste command outputs, links to commits/PRs, screenshots, etc. -->
<!-- Keep this short and relevant to acceptance. -->

- Stage 2 rollup: 171 tests plus Ruff and strict `mypy src` passed; `signal_below` produced 30 decodable segment files and a manifest.
- `0b831cf` — structured sync/async streaming implementation and acceptance tests.
- `.venv/bin/python -m pytest -q` — 178 passed; Ruff and strict `mypy src` passed.
- Comprehensive trace — 36 ordered chunks: 30 attributed audio chunks and 6 pause/marker/note events.
- `ed77a8d` — streaming transport reads only on demand and closes its underlying response; direct transport tests verify first read before EOF and bounded provider lookahead.
- `.venv/bin/python -m pytest -q` — 180 passed after transport hardening.
- Checkpoint 3.1 review: 26 focused streaming/provider/source-form tests passed; `57eca2f` adds the final HTTP failure/cleanup probe.
- `7a921fb` — content-addressed request/segment identities, validated atomic records, cache-aware rendering, and incremental-regeneration coverage.
- `.venv/bin/python -m pytest tests/test_cache.py -q` — 8 passed; incremental integration probe passed with call counts 4 initial + 3 continuity-dependent misses.
- `.venv/bin/python -m pytest -q` — 190 passed; Ruff and strict `mypy src` passed.
- Checkpoint 3.2 review: 8 cache tests and the incremental integration probe passed; `8f364ed` verifies separate cache instances under concurrent replacement.
- `b41873a` — diagnostic/security/failure-recovery implementation; pushed to `origin/main`.
- `.venv/bin/python -m pytest tests/test_security.py tests/test_failures.py tests/test_cli.py -q` — 23 passed.
- `.venv/bin/python -m pytest -q` — 202 passed; Ruff and strict `mypy src` passed.
- Adversarial corrupt-audio probe — `DecodeError DECODE_ERROR audio_assembly {'output_format': 'wav_16000'}`; request/segment/provider context is missing.
- `54d9d8a` — request-aware diagnostic enrichment for file generation, assembly, output writing, and streaming; pushed to `origin/main`.
- `.venv/bin/python -m pytest tests/test_failures.py tests/test_security.py tests/test_streaming.py -q` — 26 passed; corrupt file/stream audio assertions include full safe attribution.
- `.venv/bin/python -m pytest -q` — 204 passed; Ruff and strict `mypy src` passed.
- Unexpected stream-adapter probe — `RuntimeError adapter leaked stream-secret`; no stable code, phase, redaction, or request attribution.
- `8723b92` — symmetric provider-failure normalization for streaming; pushed to `origin/main`.
- `.venv/bin/python -m pytest tests/test_failures.py tests/test_streaming.py tests/test_security.py -q` — 28 passed, including unexpected stream fault redaction and cancellation propagation.
- `.venv/bin/python -m pytest -q` — 206 passed; Ruff and strict `mypy src` passed.
- Checkpoint 3.3 review: 27 focused tests passed; corrupt audio and unexpected stream failures retain stable redacted attribution, cancellation propagates, and no code-review improvements remain.
- `7a5662e` — documentation/package/release implementation; pushed to `origin/main`.
- `.venv/bin/python -m pytest tests/test_docs_examples.py tests/test_design_examples.py tests/test_public_contracts.py -q` — 20 passed; README quick start and both comprehensive layouts render through the fake provider.
- `.venv/bin/python -m build && .venv/bin/python tools/check_dist.py dist` — verified `elscript-0.1.0a0-py3-none-any.whl` and `elscript-0.1.0a0.tar.gz`; fresh wheel install/import/CLI/render smoke passed outside the checkout.
- `.venv/bin/python -m pytest -q` — 210 passed; Ruff and strict `mypy src` passed.
- `98509f2` — PyPI-safe absolute README links plus Twine validation in the release workflow; pushed to `origin/main`.
- PyPI project lookup — `https://pypi.org/project/elscript/` is an unrelated `0.0.1` project owned by `EliotScript` (released 2022-01-23).
- Candidate lookup — PyPI returned no project for `elscript-audio`, `elscript-tts`, or `elevenlabs-elscript` on 2026-08-14; names remain unreserved until successfully registered.
- `71f3627` — `elscript-audio` distribution metadata/docs/CI/checker; publication remains explicitly deferred.
- Isolated build/Twine/check/install smoke — verified `elscript_audio-0.1.0a0-py3-none-any.whl`, `elscript_audio-0.1.0a0.tar.gz`, installed distribution metadata, `import elscript`, CLI help, and one fake render.
- `ce8d02d` — sibling `RenderCache` instances now share a per-root lock; the previously flaky contention test passed 10 consecutive runs.
- `.venv/bin/python -m pytest -q` — 210 passed after distribution rename and cache concurrency hardening; Ruff and strict mypy passed.
- Adversarial distribution probe — fresh metadata maps `elscript` to `elscript-audio`, and no distribution named `elscript` is installed; 12 focused docs/cache tests passed.
- `d5210cc` — final review clarifies the chosen local distribution identity and removes line-wrap brittleness from its documentation assertion.
- Plan exhausted: all Stage 3 checkpoints are complete; PyPI publication and paid provider smoke remain explicitly deferred.
- `afec37c` — current action majors, 12-job OS/Python test matrix, Python 3.14 artifact build, classifiers/support docs, and CI boundary assertions.
- `.venv/bin/python -m pytest -q` — 211 passed; Ruff and strict mypy passed; isolated build, Twine, and distribution-content checks verified both `elscript_audio` artifacts.
- GitHub Actions run `31858638239` — 13/13 checks passed across Linux/macOS/Windows and CPython 3.11–3.14 with zero annotations.

## Workflow state
<!-- Dispatcher flags. Checked = active/needed. Cleared by the loop that handles each flag. -->
- [x] RUN_CONTEXT_CAPTURE
- [x] STAGE_DESIGNED
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
- 2026-08-14: Auto streaming uses independently attributable speech requests; explicit dialogue streams buffer one provider request for timestamp-based segment attribution, while HTTP response consumption remains incremental and closeable.
- 2026-08-14: File renders share a local content cache at `<output-parent>/.cache/elscript`; streaming stays write-free, and cache keys exclude logical/output identity while including material provider and continuity inputs.
- 2026-08-14: Use `elscript-audio` as the distribution name while retaining the `elscript` import package and CLI command; do not publish, tag, or create a release until a new explicit operator instruction authorizes it.
