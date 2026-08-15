# Render manifest contract

File rendering writes `<sanitized-script-id>.manifest.json` by default and returns the
same information as structured `RenderResult` fields. The current manifest contract is
`manifest_version: "1.0"`.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `manifest_version` | Manifest schema version. |
| `elscript_version` | Source-language version. |
| `script_id` | Logical script identity. |
| `provider`, `models` | Effective provider and used models. |
| `output_mode`, `output_format` | Materialized output layout and codec. |
| `duration_seconds` | Full authored timeline duration. |
| `effective_settings` | Public, redacted effective settings. |
| `files` | Generated file names, duration, and optional scene/segment identity. |
| `scenes` | Scene spans and associated files. |
| `timeline` | Ordered speech, pause, marker, and note events. |
| `segments` | Logical authored segments and resolved performance. |
| `provider_requests` | Provider grouping, timing, IDs, and cache status. |
| `alignments` | Optional original/normalized character timing. |
| `voice_segments` | Optional dialogue voice attribution. |
| `warnings` | Stable warning code, phase, message, location, and safe context. |

Fields whose values are unavailable are omitted from serialized JSON.

## Time coordinate systems

`timeline_start_seconds` and `timeline_end_seconds` use the full authored timeline,
including explicit pauses. `file_start_seconds` and `file_end_seconds` use the relevant
generated file. They are equal in single-file mode, scene-relative in scene mode, and
segment-relative in segment mode.

Segment `start_seconds`/`end_seconds` refer to the authored timeline. A segment may map
to multiple render requests when provider limits split its prepared text.

## Events

The `timeline` array preserves:

- speech identity and timing;
- exact explicit pause duration;
- marker name and timeline position;
- note position, with note text only when source-text inclusion is enabled.

Segment mode does not create standalone pause files; the manifest is the ordering
contract for reconstructing the authored timeline.

## Cache identity and status

Each segment may include a one-way `render_fingerprint`. Each provider request includes
`cache_status`, such as `hit`, `miss`, `corrupt`, or an `_unstored` variant. Credentials
and output names are excluded from fingerprints.

## Privacy and compatibility

- Credentials and sensitive-key values are recursively redacted.
- `include_source_text: false` omits authored speech/note text.
- Existing manifest files are never overwritten.
- Consumers should branch on `manifest_version`, ignore ordering of object keys, and
  tolerate new optional fields within a compatible manifest version.

See [Troubleshooting](troubleshooting.md) for safe failure reporting.
