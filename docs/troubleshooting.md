# Troubleshooting ELScript

ELScript diagnostics use this stable CLI shape:

```text
elscript: error [phase/CODE]: message at source, $.yaml.path (context)
Correction: concrete next action
```

Warnings use the same `phase/CODE` key. Treat a code as the automation contract;
wording and provider detail may become more specific over time. Credentials are never
needed in a bug report. Remove them from source excerpts and do not pass them through
an `api` mapping.

## Pipeline phases

| Phase | What failed | First check |
| --- | --- | --- |
| `source_discovery` | Source selection, file discovery, or configuration input | Check the source and `.env` paths and select exactly one source form. |
| `yaml_parsing` | YAML syntax or safe-structure limits | Check the reported line/column and remove recursive or excessive aliases. |
| `logical_merge` | Multi-file project merge | Find both definitions of the reported YAML path and remove the conflict. |
| `schema_validation` | ELScript 1.0 field shape or type | Correct the reported YAML path to match the documented schema. |
| `reference_validation` | Character, preset, or logical-ID reference | Define the missing target or correct the reference. |
| `semantic_compilation` | Stateful script semantics | Correct the reported `set`, `with`, or `reset` transition. |
| `capability_validation` | Provider/model/endpoint support | Choose supported settings; required intent is never silently dropped. |
| `provider_generation` | Authentication, account, transport, or provider response | Correct the reported provider condition before retrying. |
| `audio_assembly` | Audio decoding, timing attribution, or assembly | Regenerate corrupt provider/cache audio and inspect timing metadata. |
| `output_writing` | Naming, collision, permission, or storage failure | Use a writable empty destination with sufficient space. |

## Error codes

| Code | Typical correction |
| --- | --- |
| `ELSCRIPT_ERROR` | Use the phase and attached context to correct the input or environment. |
| `INPUT_ERROR` | Supply exactly one readable ELScript source and valid input options. |
| `SOURCE_NOT_FOUND` | Correct or create the source path. |
| `INVALID_YAML` | Correct syntax at the reported line/column; remove recursive aliases. |
| `MERGE_ERROR` | Remove incompatible project fragments. |
| `MERGE_CONFLICT` | Keep one value or make duplicate definitions identical. |
| `SCHEMA_ERROR` | Correct the reported field and value type. |
| `VALIDATION_ERROR` | Correct the reported YAML path or conflicting reference. |
| `COMPILE_ERROR` | Correct the identified script state transition. |
| `UNKNOWN_CHARACTER` | Define the character or correct the speaker name. |
| `UNKNOWN_PRESET` | Define the preset or correct its reference. |
| `INVALID_STATE` | Correct the reported `set`, `with`, or `reset` command. |
| `CAPABILITY_ERROR` | Remove or change the unsupported provider option. |
| `UNSUPPORTED_MODEL_FEATURE` | Select a compatible model or remove the required feature. |
| `UNSUPPORTED_OUTPUT_FORMAT` | Select a format supported by the planned endpoint. |
| `PROVIDER_LIMIT` | Reduce/split the request or remove excess options. |
| `PROVIDER_ERROR` | Inspect safe provider context and correct the cause before retrying. |
| `AUTHENTICATION_ERROR` | Set a valid credential in `.env`, the process environment, or the explicit secure credential input. |
| `RATE_LIMIT_ERROR` | Wait for provider capacity/quota and retry. |
| `PROVIDER_ACCOUNT_ERROR` | Resolve provider billing, plan, subscription, or quota status. |
| `GENERATION_ERROR` | Check provider availability and the reported request context. |
| `AUDIO_ERROR` | Verify provider audio and output-format compatibility. |
| `DECODE_ERROR` | Regenerate the result or remove its corrupt cache record. |
| `ASSEMBLY_ERROR` | Verify provider timing metadata and compatible audio formats. |
| `OUTPUT_ERROR` | Use a writable, collision-free output directory. |
| `FILENAME_COLLISION` | Rename colliding script, scene, segment, or character identifiers. |
| `WRITE_ERROR` | Remove collisions and check permissions and free space. |

## Warning codes

Warnings describe recoverable approximation or uncertainty. Conflicts, missing
references/voices, credentials, and unsupported required intent remain errors.

| Code | Meaning and action |
| --- | --- |
| `ELEVENLABS_INTENSITY_APPROXIMATED` | Intensity has no exact provider control; audition and adjust. |
| `ELEVENLABS_ENERGY_APPROXIMATED` | Energy has no exact provider control; audition and adjust. |
| `ELEVENLABS_SEMANTIC_TAG_EXPERIMENTAL` | Provider-tag behavior may vary; audition on the selected model. |
| `ELEVENLABS_IPA_ALIAS_FALLBACK` | An alias approximates IPA; review it or use a pronunciation dictionary. |
| `ELEVENLABS_LANGUAGE_NORMALIZATION_UNVERIFIED` | Set a supported language or disable language normalization. |
| `ELEVENLABS_SEED_BEST_EFFORT` | Seeded generation is not guaranteed byte-identical by the provider. |

## Safe retry and cleanup

- ELScript preflights all final names before provider generation and never overwrites an
  existing audio file or manifest.
- Audio and manifest bytes are staged and then atomically published. A failure or
  cancellation removes files created by that render; an older render is not modified.
- Provider results enter the content cache only after audio assembly and manifest
  validation. Invalid, incomplete, or corrupt cache records are ignored and repaired by
  a successful later render.
- The local cache is `<output-parent>/.cache/elscript`. Deleting a cache record is safe;
  the next render regenerates only its continuity-dependent request set.

When reporting a provider failure, include the diagnostic code, phase, request/segment
IDs, and provider request ID when present. Never include an API key or authorization
header.
