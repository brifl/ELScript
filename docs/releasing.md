# Release checklist

This checklist is intentionally manual at the publication boundary. CI verifies the
candidate; publishing, tagging, and paid provider calls require an explicit operator
decision.

The distribution name is `elscript-audio`; the import package and console command are
both `elscript`. Publication is currently deferred. Section 5 requires a new explicit
operator instruction and is not authorized by completing the earlier sections.

## 1. Candidate metadata

- [ ] Choose the version and update both `pyproject.toml` and
  `src/elscript/__init__.py`.
- [ ] Move user-visible changes from the Unreleased section of `CHANGELOG.md` into a
  dated release section.
- [ ] Confirm the Python requirement, classifiers, dependencies, license, project URLs,
  and console entry point.
- [ ] Confirm that `elscript-audio` is available/owned on the intended index immediately
  before publication.

## 2. Provider capability review

- [ ] Review current ElevenLabs speech, speech-with-timestamps, streaming, dialogue,
  dialogue-with-timestamps, models, formats, request limits, and retention/account rules.
- [ ] Compare them with `elevenlabs_capabilities()` and `docs/providers.md`.
- [ ] Update only the adapter/capability layer when upstream mechanics change; do not
  silently change portable ELScript semantics.
- [ ] Record the review date in the capability version and provider documentation.

## 3. Deterministic local verification

From a clean checkout and supported Python:

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m mypy src
python -m pytest -q
python -m build
python -m twine check dist/*
python tools/check_dist.py dist
```

- [ ] Confirm CI passes on Linux, macOS, and Windows for every supported Python version.
- [ ] Install the built wheel (not the source tree) in a fresh virtual environment.
- [ ] Import `elscript`, run `elscript --help`, and render the quick start with the fake
  provider.
- [ ] Confirm the wheel contains the typed package, console entry point, metadata, and
  license; confirm the sdist contains public docs, tests, and the distribution checker
  but excludes agent/workflow state.

## 4. Opt-in credentialed smoke

Do not make paid calls in default CI.

- [ ] Obtain explicit approval to incur a small ElevenLabs charge.
- [ ] Supply `ELEVENLABS_API_KEY` only through the environment or an untracked `.env`.
- [ ] Run one minimal speech request, one timestamped request, and one short two-voice
  dialogue/stream request using owned voice IDs and an allowed format.
- [ ] Inspect decoded audio, attribution/timestamps, coded warnings, the redacted
  manifest, and provider request IDs.
- [ ] Remove smoke outputs and credentials from the working directory before release.

If credentials, approval, account access, or owned voice IDs are unavailable, record the
smoke as deferred; never substitute an unapproved call.

## 5. Publication (deferred until explicitly authorized)

- [ ] Review `git diff`, `git status`, and the exact candidate commit.
- [ ] Create and sign the version tag according to project policy.
- [ ] Upload only the verified files from `dist/` to the intended index.
- [ ] Verify the index metadata and install the published wheel in another fresh
  environment.
- [ ] Publish release notes from `CHANGELOG.md` and retain the artifact checksums.
