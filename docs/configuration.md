# Configuration and security

ELScript resolves one effective configuration for file, YAML-text, mapping, directory,
and streaming entry points.

## Precedence

From highest to lowest priority:

1. explicit Python `options` or CLI flags;
2. YAML `render` and `export` values;
3. process environment;
4. `.env`;
5. library defaults.

Only explicitly supplied values override lower layers.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `ELEVENLABS_API_KEY` | ElevenLabs credential; never serialized. |
| `ELSCRIPT_PROVIDER` | Provider ID; defaults to `elevenlabs`. |
| `ELSCRIPT_MODEL` | Provider model; defaults to `eleven_v3`. |
| `ELSCRIPT_LANGUAGE` | Optional language code. |
| `ELSCRIPT_RENDER_MODE` | `auto`, `speech`, or `dialogue`. |
| `ELSCRIPT_OUTPUT_FORMAT` | Provider format such as `mp3_44100_128`. |
| `ELSCRIPT_OUTPUT_MODE` | `single`, `scene`, or `segment`. |
| `ELSCRIPT_TIMESTAMPS` | Boolean timestamp request. |
| `ELSCRIPT_SEED` | Integer best-effort seed. |
| `ELSCRIPT_TEXT_NORMALIZATION` | `auto`, `on`, or `off`. |
| `ELSCRIPT_LANGUAGE_TEXT_NORMALIZATION` | Boolean provider normalization option. |
| `ELSCRIPT_ENABLE_LOGGING` | Boolean provider request-history setting. |
| `ELSCRIPT_NORMALIZE_LOUDNESS` | Boolean local output normalization. |

Accepted boolean strings are validated; empty values explicitly clear a lower `.env`
value rather than being silently ignored.

## `.env` discovery

If `env_file` is passed to a Python entry point or `--env-file` is passed to the CLI,
that exact file is used. Otherwise ELScript checks:

1. the source file's parent or source directory;
2. the current working directory;
3. no `.env` file when neither location contains one.

Process environment values override `.env` values.

## Python options

Use `RenderOptions` or a mapping:

```python
from elscript import RenderOptions, render

result = render(
    source="story.yaml",
    output_dir="audio",
    options=RenderOptions(
        output_mode="segment",
        output_format="wav_44100",
        timestamps=True,
    ),
)
```

Mapping keys follow the `RenderOptions` field names. `None` means that the explicit
layer did not supply a value.

## CLI overrides

The CLI intentionally exposes a small file-rendering surface:

```text
elscript SOURCE [--output DIRECTORY] [--mode MODE] [--model ID]
                [--format FORMAT] [--seed INTEGER] [--env-file PATH]
```

Streaming and the wider option surface remain Python-only.

## Secrets

- Put `ELEVENLABS_API_KEY` in the process environment or a non-committed `.env` file.
- Never put credentials in YAML or any `api` mapping; validation rejects sensitive keys.
- Manifests, cache identities, exceptions, and public configuration representations
  redact credentials.
- Do not include credentials or authorization headers in issue reports.

## Privacy-related output controls

`export.manifest.enabled` controls manifest creation.
`export.manifest.include_source_text: false` removes authored source text from manifests
and note-event metadata. The `export.metadata` flags control provider request IDs,
voice segments, and character-alignment retention.

`render.enable_logging: false` requests ElevenLabs zero-retention mode. This is a
provider/account capability, and it conflicts with request stitching because provider
history is unavailable. ELScript validates that conflict before generation.

## Cache

File renders use `<output-parent>/.cache/elscript`. Cache keys include material audio
inputs and continuity dependencies but exclude credentials, output paths, and unrelated
metadata. Streaming performs no cache or filesystem writes.
