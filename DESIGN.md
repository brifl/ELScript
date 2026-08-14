# ELScript Design

**Document status:** baseline design specification  
**Script format:** ELScript 1.0  
**Primary provider:** ElevenLabs  
**API assumptions reviewed:** 2026-08-14

This document defines the contracts and observable behavior of ELScript. It is intended to be sufficiently precise for an engineer to build the library while leaving implementation details, dependency selection, class layout, and internal algorithms to the implementation.

Normative terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** describe required or recommended behavior.

---

## 1. Purpose

ELScript is a Python library and CLI for authoring and rendering expressive speech scripts.

The system is intended to support:

- robot voices and interactive speech
- game characters
- story narration
- scripted voice acting
- multi-character scenes
- reusable voice and performance definitions
- long-form audio production
- programmatic and streamed generation

The authoring language must remain readable to humans and suitable for hand editing.

The script model separates:

1. **semantic intent** — character, emotion, intensity, pace, delivery, pronunciation, scene structure
2. **provider mechanics** — ElevenLabs model IDs, voice settings, audio tags, endpoint constraints, request stitching, output formats

The provider layer is responsible for translating semantic intent into the best available mechanism for the selected provider and model.

---

## 2. Design principles

### 2.1 Human-readable source

Common dialogue should be concise:

```yaml
- MARA: "Where are we?"
- ORION: "Below the station."
```

Changes should state only what changed:

```yaml
- MARA:
    set:
      emotion: frightened
      intensity: 0.7
    say: "That isn't possible."

- ORION: "It appears to be possible."

- MARA:
    set:
      intensity: 0.9
    say: "How far below?"
```

Mara remains frightened. The final line changes only intensity.

### 2.2 Sticky state, sparse authoring

Performance parameters are persistent per character within a scene unless explicitly temporary or reset.

The source should not repeat unchanged emotional/performance parameters.

### 2.3 Provider independence

Core script semantics MUST NOT depend on ElevenLabs syntax.

For example:

```yaml
emotion: frightened
volume: whisper
```

is preferred to:

```text
[frightened] [whispers]
```

The latter remains available through explicit raw tags.

### 2.4 No silent loss of intent

If a script or caller requests a setting that cannot be honored by the selected provider/model, ELScript MUST either:

- fail with a useful capability/validation error, or
- issue an explicit documented warning when degradation is permitted

It MUST NOT silently ignore unsupported settings.

### 2.5 One logical pipeline

Single files, directories, YAML strings, parsed mappings, CLI calls, normal rendering, and streaming all converge onto the same canonical document, validation, compilation, and render planning behavior.

### 2.6 Stable external contracts

Provider API changes should normally require changes only in:

- provider capability discovery
- provider-specific validation
- prompt/tag translation
- provider request generation

They should not require rewriting the source language or project documents.

---

## 3. Terminology

### Document

The complete logical ELScript input after loading and merging all source fragments.

### Character

A named speaker with a voice, defaults, optional preset, and optional provider-specific settings.

### Scene

An ordered collection of script entries. Scene boundaries are meaningful for state reset, output mode, rendering, context, and manifest organization.

### Script entry

One ordered item in `scene.script`, such as:

- character speech
- pause
- marker
- editorial note

### Utterance / turn

One character-owned script entry.

```yaml
- MARA:
    say: "Hello."
```

### Speech segment

The smallest authored vocal unit with a single resolved performance/provider state.

A scalar utterance normally produces one speech segment.

A structured `say` may produce multiple speech segments:

```yaml
- MARA:
    say:
      - text: "I thought you'd gone."
      - set:
          emotion: relieved
      - text: "But you're here."
```

The two text items are separate speech segments because resolved performance changes between them.

A cue-only vocal event may also form a speech segment.

### Render request

One provider request. A render request MAY contain one or multiple speech segments.

Provider request boundaries are an implementation/render-planning concern and are not equivalent to authored speech-segment boundaries.

### Render unit

A provider-generated audio result associated with one render request.

### Performance state

The resolved semantic delivery state for a character at a specific point in the script.

### Provider options

Raw provider-specific settings that are outside the portable ELScript semantic model.

---

## 4. High-level behavioral pipeline

The observable processing model is:

```text
source
  ↓
load individual YAML document(s)
  ↓
logical merge
  ↓
schema validation
  ↓
configuration resolution
  ↓
semantic compilation / state resolution
  ↓
provider capability validation
  ↓
render planning / request grouping
  ↓
provider generation
  ↓
audio assembly or streaming
  ↓
output files + manifest
```

After logical merge, later stages MUST behave identically regardless of whether the source originated as:

- one YAML file
- a directory
- a YAML string
- a parsed Python mapping

---

# Part I — Invocation and configuration

## 5. Python API contract

The library SHOULD expose one canonical render entry point plus convenience functions.

Conceptual signatures:

```python
render(
    *,
    source: str | Path | None = None,
    yaml_text: str | None = None,
    document: Mapping[str, Any] | None = None,
    output_dir: str | Path,
    options: RenderOptions | Mapping[str, Any] | None = None,
    env_file: str | Path | None = None,
) -> RenderResult
```

Exactly one of the following MUST be supplied:

- `source`
- `yaml_text`
- `document`

`source` MAY identify either a YAML file or a directory.

Convenience functions MAY include:

```python
render_yaml(yaml_text, ...)
render_document(document, ...)
```

They MUST delegate to the canonical pipeline rather than reimplementing behavior.

### 5.1 Streaming API

Streaming is available only through the Python library.

Recommended public contracts:

```python
stream(
    *,
    source=None,
    yaml_text=None,
    document=None,
    options=None,
    env_file=None,
) -> Iterator[AudioChunk]
```

```python
astream(
    *,
    source=None,
    yaml_text=None,
    document=None,
    options=None,
    env_file=None,
) -> AsyncIterator[AudioChunk]
```

Streaming MUST accept the same source forms and effective render configuration as file rendering.

Streaming does not require `output_dir`.

The implementation MAY expose a `stream=True` convenience on another API, but explicit `stream()` / `astream()` entry points are preferred because they preserve a stable return type.

---

## 6. CLI contract

Conceptual command:

```bash
elscript SOURCE
```

`SOURCE` MAY be:

- one `.yaml` / `.yml` file
- a directory

Basic options:

```text
--output DIRECTORY
--mode single|scene|segment
--model MODEL_ID
--format OUTPUT_FORMAT
--seed INTEGER
--env-file PATH
```

Additional render options MAY be added as the library evolves.

CLI options use the same configuration keys and semantics as Python options.

### 6.1 No CLI streaming

The CLI MUST NOT expose streamed audio output.

There should be no `--stream` mode.

The CLI exists for producing file outputs, diagnostics, and manifests.

### 6.2 Thin-wrapper rule

The CLI MUST invoke the same public/core pipeline used by Python.

The CLI MUST NOT:

- interpret ELScript independently
- merge folders differently
- apply different state rules
- use a separate provider adapter
- use separate filename semantics

---

## 7. Output directory

For file rendering, `output_dir` is always a directory.

The caller MUST NOT supply a full destination filename as `output_dir`.

The library determines generated filenames from:

- script identity
- output mode
- scene ID
- speech-segment ordinal
- speaker
- resolved output format

The library MUST create the output directory when it does not exist, provided its parent location is writable.

Existing-file overwrite policy SHOULD be configurable. The default SHOULD avoid silent destructive replacement unless the file is known to be an output of the same render identity.

---

## 8. Configuration precedence

Effective configuration is resolved leaf-by-leaf in this order:

```text
1. explicit Python arguments / CLI arguments
2. YAML configuration
3. process environment
4. .env
5. library defaults
```

A missing value at one level falls through to the next level.

An explicit false/zero/empty value is not considered missing.

Example:

```dotenv
ELSCRIPT_MODEL=eleven_multilingual_v2
ELSCRIPT_OUTPUT_FORMAT=mp3_44100_128
```

```yaml
render:
  model: eleven_v3
```

```python
options = {
    "output_format": "mp3_44100_192"
}
```

Result:

```text
model         = eleven_v3
output_format = mp3_44100_192
```

### 8.1 Environment variables

At minimum, support:

```dotenv
ELEVENLABS_API_KEY=
ELSCRIPT_PROVIDER=elevenlabs
ELSCRIPT_MODEL=
ELSCRIPT_OUTPUT_FORMAT=
ELSCRIPT_OUTPUT_MODE=
ELSCRIPT_TEXT_NORMALIZATION=
ELSCRIPT_ENABLE_LOGGING=
```

Additional values MAY be represented with a consistent `ELSCRIPT_` namespace.

### 8.2 `.env` discovery

If `env_file` is explicitly supplied, it is used as the `.env` source.

Otherwise:

1. for a path source, search for `.env` at the source root:
   - file source: containing directory
   - directory source: that directory
2. if none exists there, check the current working directory
3. if none exists, continue without a `.env` file

Process environment variables override values loaded from `.env`.

The implementation SHOULD expose the chosen `.env` path in diagnostics/debug metadata.

### 8.3 Credentials

API credentials MUST NOT be required or encouraged inside ELScript YAML.

The standard ElevenLabs credential key is:

```dotenv
ELEVENLABS_API_KEY=
```

An explicit programmatic credential MAY override environment configuration.

Credentials MUST NOT appear in:

- output manifests
- error messages
- logs
- cache keys in reversible form

---

# Part II — Source loading and merge semantics

## 9. Single-file input

A file source MUST:

1. parse as YAML using a safe loader
2. contain a mapping at the root
3. be validated as an ELScript document or fragment
4. retain source-location metadata for diagnostics where practical

Arbitrary Python object construction through YAML MUST NOT be allowed.

---

## 10. Directory input

A directory source represents one logical ELScript document composed from multiple files.

### 10.1 File discovery

The loader recursively includes:

```text
*.yaml
*.yml
```

It SHOULD ignore:

- hidden files
- hidden directories
- common build/output directories
- `.env`
- non-YAML files

Exact exclusion rules should be documented and configurable if necessary.

### 10.2 Deterministic traversal

Files MUST be processed in deterministic order using normalized relative paths.

Filesystem enumeration order MUST NOT affect the logical document.

### 10.3 Parse first, merge second

Files MUST NOT be concatenated as YAML text.

Each source file is parsed independently into a YAML structure. Structures are then logically merged.

This avoids:

- duplicate YAML document headers
- indentation coupling
- anchor/alias leakage across files
- accidental key replacement
- parser behavior dependent on concatenation order

---

## 11. Logical merge rules

The merged document is conceptually equivalent to one source document.

### 11.1 Conflict principle

Source-file ordering MUST NOT silently decide conflicting definitions.

When two fragments define the same scalar leaf:

- identical values are compatible
- different values are a merge conflict unless a section-specific rule explicitly permits replacement

A conflict should identify:

- logical path
- both values
- both source files/locations where available

Example:

```text
MergeConflictError:
characters.ALLEN.voice_id differs between
characters/allen.yaml and characters/alternate.yaml
```

### 11.2 Top-level merge behavior

| Section | Merge rule |
|---|---|
| `elscript` | all defined values MUST agree |
| `meta` | deep merge, conflicts error |
| `render` | deep merge, conflicts error |
| `export` | deep merge, conflicts error |
| `pronunciation` | structured merge |
| `presets` | merge by preset ID, then deep merge |
| `characters` | merge by character ID, then deep merge |
| `scenes` | concatenate, then order |
| unknown extension sections | defined by extension; otherwise validation error |

### 11.3 Mapping merge

Mappings recursively union keys.

```yaml
# a.yaml
characters:
  MARA:
    voice_id: abc
```

```yaml
# b.yaml
characters:
  MARA:
    defaults:
      emotion: calm
```

Merged:

```yaml
characters:
  MARA:
    voice_id: abc
    defaults:
      emotion: calm
```

### 11.4 List merge

Lists do not have one universal merge operation.

Section/schema semantics determine behavior.

Examples:

- `scenes`: concatenate
- `meta.tags`: stable union MAY be used
- `delivery`: is a semantic list and is not automatically unioned across conflicting definitions
- pronunciation dictionary references: preserve declared order and reject incompatible duplicates

### 11.5 Scene IDs

Scene IDs MUST be unique after merge.

Two scene objects with the same `id` are an error. Scenes are not implicitly deep-merged.

This makes scene authorship and order unambiguous.

---

## 12. Scene ordering

Each scene MAY specify:

```yaml
order: 20
```

Final order is determined by:

1. explicit `order`, ascending
2. deterministic source path order
3. position within the source file

Scenes with no explicit order preserve deterministic source ordering.

If explicit and implicit order values are mixed, explicit `order` values determine their relative numeric placement, while unspecified scenes use stable source ordering according to a documented fallback.

Implementations SHOULD warn about ambiguous mixed ordering if the resulting position is likely surprising.

A project's filenames may therefore use conventional prefixes:

```text
010_intro.yaml
020_restaurant.yaml
030_basement.yaml
```

but filename prefixes are only a convenience. `scene.order` is the semantic ordering field.

---

# Part III — ELScript 1.0 schema

## 13. Top-level schema

Canonical shape:

```yaml
elscript: "1.0"

meta: {}
render: {}
pronunciation: {}
presets: {}
characters: {}
scenes: []
export: {}
```

Only `elscript`, `characters`, and `scenes` are conceptually central, but validation MAY allow character-free metadata fragments before merge.

The fully merged renderable document MUST contain all information required to resolve every spoken character.

---

## 14. `elscript`

```yaml
elscript: "1.0"
```

Required for a complete document.

Fragments MAY omit it.

If multiple fragments specify it, all values MUST agree.

Major-version incompatibility MUST fail before rendering.

---

## 15. `meta`

Example:

```yaml
meta:
  id: signal-below
  title: "The Signal Below"
  description: "A short dramatic scene."
  author: "Example Author"
  language: en
  tags: [science-fiction, demo]
```

### Fields

| Field | Type | Meaning |
|---|---|---|
| `id` | string | stable script identifier |
| `title` | string | human title |
| `description` | string | optional description |
| `author` | string | optional attribution |
| `language` | string | default language, typically ISO 639-1 |
| `tags` | list[string] | organizational metadata |

`meta.id` is the preferred base name for single-file output and manifests.

Fallback identity order:

1. `meta.id`
2. slugified `meta.title`
3. source file/directory name
4. `output`

---

## 16. `render`

Example:

```yaml
render:
  provider: elevenlabs
  mode: auto
  model: eleven_v3
  output_format: mp3_44100_192
  timestamps: true
  seed: null
  text_normalization: auto
  language_text_normalization: false
  enable_logging: true

  chunking:
    max_chars: 1800
    prefer_scene_boundaries: true
    prefer_utterance_boundaries: true
    preserve_continuity: true
```

### Core fields

| Field | Meaning |
|---|---|
| `provider` | provider adapter ID |
| `mode` | provider rendering strategy: `auto`, `speech`, or `dialogue` |
| `model` | default provider model ID |
| `output_format` | provider/output format |
| `timestamps` | request/retain timing metadata when available |
| `seed` | best-effort generation seed |
| `text_normalization` | `auto`, `on`, `off` |
| `language_text_normalization` | provider-specific language normalization request |
| `enable_logging` | provider request-history/logging behavior |
| `chunking` | render-planning hints |

### `mode`

#### `auto`

The planner selects appropriate provider endpoints based on:

- number of speakers
- model support
- continuity needs
- streaming
- chunk size
- provider capabilities

#### `speech`

Prefer single-speaker text-to-speech requests.

The planner may still combine compatible authored segments where provider behavior permits without violating output contracts.

#### `dialogue`

Prefer native multi-speaker dialogue requests.

If unsupported by the model/provider, validation fails unless an explicitly configured degradation policy permits fallback.

### Chunking

`chunking.max_chars` is a planning ceiling, not a promise to send exactly that amount.

The planner MUST also honor provider hard/recommended limits.

For ElevenLabs Text-to-Dialogue as of 2026-08-14:

- maximum unique voice IDs per request: 10
- reliable total `inputs[].text` target: no more than 2,000 characters

A conservative default such as 1,800 characters is therefore appropriate, but the provider adapter remains authoritative.

---

## 17. `pronunciation`

Example:

```yaml
pronunciation:

  dictionaries:
    - id: dictionary_id
      version_id: version_id

  terms:
    Calypso:
      ipa: "kəˈlɪpsoʊ"

    XJ-9:
      say_as: "X J Nine"
```

### 17.1 Dictionary references

```yaml
dictionaries:
  - id: ...
    version_id: ...
```

The provider adapter sends these through supported pronunciation-dictionary mechanisms.

As of 2026-08-14, ElevenLabs TTS and Text-to-Dialogue accept up to three pronunciation dictionary locators per request.

If the effective configuration contains more provider dictionary references than supported, rendering MUST fail or apply an explicitly documented strategy. It MUST NOT silently drop dictionaries.

### 17.2 Terms

A term definition may include:

```yaml
Term:
  ipa: "..."
  say_as: "..."
```

`ipa` expresses precise phonetic intent.

`say_as` expresses an alias/substitution.

The adapter chooses the best mechanism for the selected provider/model.

For Eleven v3, native IPA may be compiled into:

```text
/IPA/
```

inside generated provider text.

Term matching behavior SHOULD be deterministic and SHOULD protect against replacing substrings inside unrelated words.

Case sensitivity MUST be documented. The default SHOULD be exact/case-sensitive unless a term explicitly requests otherwise.

---

## 18. `presets`

Presets are reusable semantic performance defaults.

Example:

```yaml
presets:

  narration:
    emotion: neutral
    intensity: 0.25
    energy: 0.30
    pace: measured
    volume: normal
    delivery: [warm, restrained]

  robot-calm:
    emotion: neutral
    intensity: 0.20
    energy: 0.25
    pace: measured
    volume: normal
    delivery: [precise, understated]
```

Preset IDs MUST be unique.

A preset SHOULD contain portable semantic settings.

Provider-specific settings MAY be permitted under an `api` submapping but should be used sparingly.

---

## 19. Performance state

The portable performance model is intentionally semantic.

Baseline fields:

```yaml
emotion: neutral
intensity: 0.0
energy: 0.0
pace: normal
volume: normal
delivery: []
accent: null
```

### Suggested semantics

#### `emotion`

Freeform descriptive string:

```yaml
emotion: frightened
emotion: suspicious
emotion: bittersweet
emotion: controlled anger
```

The schema SHOULD avoid a permanently closed emotion enumeration because expressive models support a broader vocabulary.

#### `intensity`

Normalized semantic strength:

```text
0.0 ... 1.0
```

This does not directly mean an ElevenLabs numeric slider.

It describes how strongly the requested performance should express the current emotion/delivery intent.

#### `energy`

Normalized semantic vocal energy:

```text
0.0 ... 1.0
```

#### `pace`

A controlled but extensible string, for example:

```text
very_slow
slow
slightly_slow
measured
normal
slightly_fast
fast
very_fast
```

Custom descriptive values MAY be allowed.

#### `volume`

Typical values:

```text
whisper
quiet
normal
loud
shout
```

#### `delivery`

A list of additional descriptive directions:

```yaml
delivery:
  - dry
  - breathless
  - trembling
```

Ordering SHOULD be preserved because it may affect provider prompting.

#### `accent`

Optional descriptive accent direction:

```yaml
accent: "strong French"
```

Provider/voice compatibility is not guaranteed.

### Extensibility

Unknown performance fields SHOULD fail schema validation unless:

- the schema version permits extension fields, or
- they are placed in an explicit extension namespace

This catches typos instead of silently discarding intent.

---

## 20. `characters`

Example:

```yaml
characters:

  NARRATOR:
    voice_id: VOICE_NARRATOR
    preset: narration
    model: eleven_v3

    defaults:
      emotion: neutral
      intensity: 0.30

    api:
      voice_settings: {}

  MARA:
    voice_id: VOICE_MARA
    preset: conversational

    defaults:
      emotion: confident
      intensity: 0.45
      energy: 0.50
      pace: normal
      volume: normal
      delivery: [natural]
```

### Character fields

| Field | Meaning |
|---|---|
| `voice_id` | provider voice identifier |
| `preset` | preset ID |
| `model` | optional model override |
| `language` | optional language override |
| `defaults` | character-specific semantic defaults |
| `api` | provider-specific escape hatch |
| `meta` | optional character metadata |

Character IDs are logical script identifiers and are distinct from provider voice IDs.

Character IDs MUST be unique.

The system MUST validate referenced preset IDs and required provider voice IDs before generation.

---

## 21. `api` provider escape hatch

Provider-specific configuration is needed for API features that do not belong in the portable semantic model.

Example:

```yaml
api:
  voice_settings:
    stability: 0.45
    similarity_boost: 0.80
    style: 0.20
    speed: 0.95
    use_speaker_boost: true
```

Or provider-specific dialogue settings:

```yaml
api:
  settings:
    ...
```

### Contract

`api` is opaque to the core schema beyond basic structure. It is interpreted by the active provider adapter.

The provider adapter MUST:

1. know which raw settings are valid for the selected endpoint/model
2. validate values where possible
3. reject unsupported settings or produce an explicit degradation warning
4. include effective raw options in render identity/cache identity
5. exclude credentials/secrets from manifests

Provider settings MAY exist at multiple scopes.

Recommended precedence within the document:

```text
render-level provider defaults
        ↓
character api
        ↓
scene api
        ↓
utterance api
        ↓
speech-segment api
```

Later/more-specific values override earlier values leaf-by-leaf.

External Python/CLI render-option overrides remain higher priority where they target the same setting.

---

## 22. `scenes`

Example:

```yaml
scenes:

  - id: basement
    order: 20
    title: "The Basement"

    context: >
      Ellis is alone in an abandoned station.

    inherit_character_state: false

    render:
      seed: 123456

    api: {}

    script:
      - NARRATOR: "At 2:17 in the morning, the station spoke."
```

### Scene fields

| Field | Meaning |
|---|---|
| `id` | unique scene ID |
| `order` | optional ordering value |
| `title` | human title |
| `context` | non-spoken scene context |
| `inherit_character_state` | state-boundary behavior |
| `render` | scene render overrides |
| `api` | provider-specific overrides |
| `script` | ordered entries |

### Scene-state boundary

Default:

```yaml
inherit_character_state: false
```

At scene start, each character's current state is reconstructed from:

1. preset
2. character defaults
3. applicable scene defaults

Persistent state mutations from the previous scene are not inherited.

If:

```yaml
inherit_character_state: true
```

the prior scene's final character states carry into this scene.

This setting does not override newly applied scene-level defaults unless the schema explicitly defines them.

---

# Part IV — Script entries and state semantics

## 23. Simple speech shorthand

```yaml
- MARA: "Where are we?"
```

Equivalent conceptual long form:

```yaml
- MARA:
    say: "Where are we?"
```

Scalar shorthand is allowed only when no additional fields are needed.

---

## 24. Persistent `set`

```yaml
- MARA:
    set:
      emotion: suspicious
      intensity: 0.55
      pace: slow
    say: "Something about this doesn't make sense."
```

`set` updates the character's persistent state before the associated speech is resolved.

The changes remain active for later utterances by that character.

Example:

```yaml
- MARA:
    set:
      emotion: suspicious
      intensity: 0.55
    say: "You said it was offline."

- ORION: "It was."

- MARA:
    set:
      intensity: 0.8
    say: "What aren't you telling me?"
```

Final Mara state includes:

```yaml
emotion: suspicious
intensity: 0.8
```

---

## 25. Temporary `with`

```yaml
- ORION:
    with:
      volume: quiet
      delivery: [confidential]
    say: "The reactor is not our main problem."
```

`with` overlays the current resolved state for the associated utterance or segment only.

After the temporary scope ends, the previous persistent state is restored.

`with` MUST NOT mutate sticky character state.

---

## 26. `reset`

Reset selected fields:

```yaml
- MARA:
    reset: [pace, intensity]
    say: "All right."
```

Reset one field MAY be accepted as scalar syntax:

```yaml
reset: intensity
```

Reset all:

```yaml
reset: all
```

Reset restores the affected field(s) to the character's baseline state for the current scene after applying:

1. preset
2. character defaults
3. scene defaults, if defined

It does not necessarily mean a hardcoded library default.

`reset` updates persistent state.

---

## 27. `cue`

`cue` expresses a semantic audible direction/event.

Examples:

```yaml
- MARA:
    cue: [exhales, nervous laugh]
    say: "Of course it isn't."
```

```yaml
- MARA:
    cue: swallows
```

A cue may:

- influence adjacent speech
- produce a non-verbal vocal event
- be translated into provider audio tags
- become a separate speech segment if it is independently audible

The compiler/provider adapter determines the exact provider prompt while preserving authored order.

Cue text is semantic rather than guaranteed raw provider syntax.

---

## 28. `tags`

`tags` is the explicit provider-oriented escape hatch for vocal/audio tags.

Example:

```yaml
- MARA:
    tags: [sarcastic]
    say: "No. Absolutely not."
```

For Eleven v3 this may compile directly to square-bracket audio tags.

Tags MUST preserve authored order.

The adapter SHOULD validate tag syntax but SHOULD NOT maintain an overly restrictive permanent allowlist, because Eleven v3 documentation describes the tag vocabulary as extensible/non-exhaustive.

Raw tags are less portable than semantic performance fields.

---

## 29. Structured `say`

A `say` value may be a scalar:

```yaml
say: "Hello."
```

or a list of ordered segment commands:

```yaml
say:
  - text: "I have detected another power source."

  - set:
      emotion: concerned
      intensity: 0.45

  - cue: long pause

  - text: "It is beneath us."
```

### Allowed structured items

A structured item MAY contain:

- `text`
- `set`
- `with`
- `reset`
- `cue`
- `tags`
- `api`

State-only commands are valid:

```yaml
- set:
    emotion: concerned
```

Text-bearing commands are valid:

```yaml
- with:
    volume: whisper
  text: "Don't move."
```

### Segment-state rules

Process structured items in authored order.

For each item:

1. apply `reset` to persistent state
2. apply `set` to persistent state
3. derive temporary state from `with`
4. apply cues/tags/api overlays
5. if the item is vocal, emit a speech segment with the resolved state
6. discard `with` after that item
7. preserve persistent `set`/`reset` for later items and later utterances

A parent utterance-level `with` forms a temporary scope around the entire utterance.

A segment-level `with` overlays that scope only for the segment.

---

## 30. State-resolution order

The effective performance for a speech segment is resolved conceptually as:

```text
library semantic defaults
        ↓
preset
        ↓
character defaults
        ↓
scene defaults
        ↓
character current persistent state
        ↓
utterance reset/set
        ↓
utterance with
        ↓
segment reset/set
        ↓
segment with
```

A `reset` does not simply erase a value. It restores the applicable baseline from earlier layers.

Provider-specific options are resolved separately using their own inheritance chain.

---

## 31. `pause`

Example:

```yaml
- pause: 1.25
```

`pause` is measured in seconds.

It is a deterministic ELScript timeline operation, not an SSML directive.

### Required behavior

For `single` and `scene` output modes:

- explicit pauses MUST be represented as inserted silence of the requested duration, subject only to normal audio encoding precision

For `segment` output mode:

- pauses MUST NOT generate standalone silent audio files by default
- pauses MUST be retained as ordered manifest timeline events
- consumers can reconstruct authored timing from the manifest

For Python streaming:

- the stream contract MUST preserve pause timing
- implementation may emit silence audio chunks or a structured pause event, but the public behavior must be documented and consistent

This separation is important because Eleven v3 does not support SSML break tags. Provider-generated conversational pauses and explicit ELScript pauses are different concepts.

---

## 32. `note`

```yaml
- note: >
    Elevator doors open. Mara sees the chamber.
```

A note is editorial metadata.

It MUST NOT be spoken.

It MAY be included in:

- diagnostics
- debug compilation output
- manifest metadata

It MUST NOT affect speech unless an explicit future feature defines such behavior.

---

## 33. `marker`

```yaml
- marker: chamber-reveal
```

Markers are named zero-duration timeline events.

They are intended for:

- games
- animation
- robot behavior
- scene triggers
- downstream editing

Markers MUST appear in the render manifest in authored order.

For assembled output, the manifest SHOULD record their best-known timeline position.

---

## 34. Entry IDs

Any speech entry MAY explicitly specify a stable ID.

Example:

```yaml
- MARA:
    id: basement.mara.question
    say: "How far below?"
```

If omitted, the compiler MUST create a deterministic logical segment ID.

Generated IDs SHOULD be stable when unrelated earlier/later content changes whenever practical.

A manifest must distinguish:

- logical ID
- ordinal position
- provider request ID

They are not interchangeable.

---

# Part V — Provider model and ElevenLabs behavior

## 35. Provider interface contract

The core system operates against a provider abstraction.

Conceptually a provider must support:

```text
capability discovery / description
validation
render request generation
normal rendering
streaming where supported
provider metadata extraction
```

The provider receives compiled/resolved segments and render plans.

The provider MUST NOT be responsible for:

- YAML parsing
- folder merging
- script state inheritance
- output filename policy
- CLI parsing

---

## 36. Provider capabilities

Capabilities should be represented explicitly rather than assumed from model names.

Examples:

```text
text_to_speech
text_to_dialogue
streaming
timestamps
speaker_segments
pronunciation_dictionaries
native_ipa
request_stitching
seed
text_normalization
language_normalization
voice_settings
audio_tags
max_dialogue_voices
recommended_request_chars
supported_output_formats
```

Capability information MAY combine:

- built-in known behavior
- live provider model metadata
- account/subscription constraints
- endpoint-specific rules

### Validation timing

Capability validation MUST occur before chargeable generation whenever possible.

---

## 37. ElevenLabs Text-to-Speech mapping

As of 2026-08-14, ElevenLabs Text-to-Speech exposes:

- voice ID
- model ID
- language code
- request-level voice settings
- pronunciation dictionary locators
- seed
- `previous_text`
- `next_text`
- previous request IDs
- next request IDs
- text normalization
- language text normalization
- multiple output formats
- timestamp variants
- streaming variants

ELScript should exploit these when useful without exposing them as mandatory authoring concepts.

### Continuity

For long-form speech split across multiple provider requests, the planner SHOULD use available continuity mechanisms such as:

- previous/next text
- previous/next request IDs

where supported and compatible with cache/regeneration behavior.

As of 2026-08-14, ElevenLabs accepts up to three previous request IDs and up to three next request IDs for TTS continuity.

---

## 38. ElevenLabs Text-to-Dialogue mapping

As of 2026-08-14, Text-to-Dialogue:

- accepts ordered `{text, voice_id}` inputs
- defaults to `eleven_v3`
- supports up to 10 unique voice IDs in one request
- recommends no more than 2,000 total characters across dialogue inputs for reliable generation
- supports language code
- dialogue settings
- pronunciation dictionary locators
- seed
- text normalization
- normal and streaming/timestamp endpoints
- can return voice-segment metadata with timestamped dialogue output

The render planner may group several ELScript speech segments into one dialogue request when:

- their provider/model settings are compatible
- total limits are respected
- output contracts can still identify authored segments
- scene boundaries and explicit pauses are honored
- grouping improves natural conversational context

The planner MUST NOT merge authored text in a way that loses speaker or segment identity.

---

## 39. Eleven v3 expressive mapping

Eleven v3 performance is strongly influenced by:

- voice choice
- contextual text
- audio tags
- punctuation
- capitalization
- text structure
- stability behavior

Semantic performance values are translated into these mechanisms by the ElevenLabs prompt builder.

Example semantic source:

```yaml
emotion: frightened
intensity: 0.75
pace: slow
volume: whisper
delivery: [trembling]
```

Possible provider prompt:

```text
[frightened] [slowly] [whispers] [trembling] ...
```

This translation is not part of the ELScript 1.0 language contract. It is provider-adapter behavior and MAY evolve.

### v3 pause behavior

Eleven v3 does not support SSML `<break>` tags.

Provider-level conversational pacing should therefore use v3-compatible prompting techniques such as:

- audio tags
- punctuation
- ellipses
- text structure

Exact authored timeline pauses use ELScript `pause` and are inserted outside the provider generation.

### v3 audio tags

ElevenLabs documents tags for emotions, vocal delivery, human reactions, and other audible events, and notes that combinations and additional descriptive tags may work differently across voices.

Therefore the adapter SHOULD:

- preserve raw authored tags
- avoid treating the documented examples as an exhaustive enum
- allow semantic-to-tag translation to evolve
- warn when a requested semantic direction is known to be incompatible with a selected model

### v3 stability

ElevenLabs currently describes v3 stability behavior using Creative, Natural, and Robust regions/modes, with Creative/Natural more responsive to expressive audio tags and Robust more consistent.

ELScript SHOULD expose this through provider configuration/capability mapping rather than baking those provider-specific labels into the portable performance schema.

---

## 40. Numeric voice settings

ElevenLabs request-level voice settings on supported TTS models include concepts such as:

- stability
- similarity boost
- style
- speed
- speaker boost

These belong under provider-specific configuration unless a portable semantic field has a clear equivalent.

Example:

```yaml
api:
  voice_settings:
    stability: 0.45
    similarity_boost: 0.80
    style: 0.20
    speed: 0.95
    use_speaker_boost: true
```

The adapter MUST determine whether those fields are valid for the selected model/endpoint.

Semantic `pace` is not necessarily equivalent to raw numeric `speed`.

---

## 41. Output formats and account capabilities

Provider format support and subscription gating are dynamic capability concerns.

As of 2026-08-14, ElevenLabs documents:

- `mp3_44100_128` as a standard default on core endpoints
- MP3 192 kbps as requiring Creator tier or above
- 44.1 kHz PCM/WAV as requiring Pro tier or above on the referenced endpoints

ELScript MUST NOT permanently assume the user's subscription.

It should:

1. validate known static format syntax
2. allow provider/account errors to be translated into useful capability errors
3. optionally query capabilities/account state when available
4. keep format policy outside the script compiler

---

# Part VI — Rendering and output contracts

## 42. Render planning

The compiler outputs fully resolved semantic speech segments.

The planner transforms them into provider requests.

The planner may consider:

- scene boundaries
- speaker changes
- model changes
- provider endpoint capabilities
- maximum voices
- recommended/hard character limits
- pronunciation dictionary set
- provider raw settings
- explicit pauses
- output mode
- streaming
- continuity context
- cache reuse

Two authored segments MAY share one provider request.

One authored segment MAY be split into multiple provider requests only when required by provider limits. If split, the manifest must still preserve its logical identity and ordered subparts.

---

## 43. Provider request boundaries vs output boundaries

These concepts are intentionally independent.

For example, a single ElevenLabs dialogue request may generate:

```text
MARA segment 12
ORION segment 13
MARA segment 14
```

In `segment` output mode, ELScript must still produce three speech-segment outputs.

How the implementation extracts/splits those files is not specified by this design; only the observable result is.

Conversely, many provider requests may be assembled into one `single` output file.

---

## 44. Output mode: `single`

Default:

```yaml
export:
  mode: single
```

Produces:

```text
<output_dir>/<script_id>.<ext>
<output_dir>/<script_id>.manifest.json
```

All scenes are assembled in final script order.

Explicit ELScript pauses are included.

Scene boundaries do not require audible silence unless authored/configured.

Filename base selection:

1. `meta.id`
2. slugified `meta.title`
3. source name
4. `output`

---

## 45. Output mode: `scene`

```yaml
export:
  mode: scene
```

Produces one audio file per scene:

```text
<scene_id>.<ext>
```

Example:

```text
arrival.mp3
restaurant.mp3
basement.mp3
```

Explicit pauses inside each scene are included.

Scene files are independently valid audio files.

Scene IDs are sanitized only as needed for filesystem safety.

If sanitization creates a collision, rendering MUST fail with a filename-collision error unless a deterministic disambiguation policy is explicitly configured.

---

## 46. Output mode: `segment`

```yaml
export:
  mode: segment
```

Produces one file per speech segment.

Required filename:

```text
<sceneId>_<sortableOrderNumber>_<speakerName>.<formatExt>
```

Example:

```text
scene01restaurant_0013_allen.mp3
```

### 46.1 Sortable ordinal

Default ordinal behavior:

- global across speech segments in the complete compiled script
- starts at 1
- zero-padded to at least four digits
- monotonically increases
- does not count notes, markers, or explicit pause entries

Example:

```text
arrival_0001_narrator.mp3
arrival_0002_mara.mp3
restaurant_0003_mara.mp3
restaurant_0004_allen.mp3
```

The implementation MAY automatically widen padding above 9,999 segments so lexical order remains numeric order.

### 46.2 Speaker name

The filename uses the logical ELScript character ID, lowercased/sanitized according to filename rules.

Provider voice names are not used.

### 46.3 Segment contents

A segment file contains the audible content of that speech segment.

Inter-entry ELScript pauses are not prepended/appended to segment files by default.

Cue-only vocal segments receive segment files if they produce audible content.

Explicit pause entries are represented as manifest events, not silent files.

---

## 47. File sanitization

Filename components MUST:

- remove/replace path separators
- prevent `.` / `..` path traversal
- avoid platform-invalid characters
- be deterministic
- preserve readability where possible

Sanitization MUST occur after logical IDs are established.

The manifest MUST retain original logical IDs even if filenames are sanitized.

---

## 48. Audio assembly

The audio assembly layer is responsible for observable timeline composition, including:

- concatenating provider audio
- inserting explicit pauses
- preserving order
- producing requested containers/codecs
- optionally normalizing audio when configured

Provider adapters return/generated audio; they do not own project-level assembly rules.

### 48.1 Loudness normalization

If supported:

```yaml
export:
  normalize_loudness: true
```

normalization applies during output assembly and must be deterministic for the same audio inputs/settings.

Normalization settings SHOULD be explicit in the manifest because they change output identity.

---

## 49. Streaming contract

`stream()` and `astream()` return structured chunks, not anonymous bytes only.

Conceptual model:

```python
AudioChunk(
    data: bytes,
    format: str,
    scene_id: str | None,
    segment_id: str | None,
    ordinal: int | None,
    speaker: str | None,
    final_for_segment: bool,
    event: str | None,
)
```

### Required semantics

Consumers must be able to determine:

- which scene is active
- which logical segment owns speech audio
- which character is speaking
- when a segment has completed

The stream may additionally expose:

- timestamps/alignment
- request IDs
- pause events
- marker events

### Ordering

Chunks/events MUST preserve authored timeline order.

### Backpressure and cancellation

The streaming API SHOULD support natural consumer backpressure.

The asynchronous API SHOULD permit cancellation without corrupting unrelated future renders.

### Streaming and files

Streaming does not implicitly write output files.

An application that wants both streaming and archival storage can write chunks itself or use a future explicit tee/output feature.

---

# Part VII — Manifest and metadata

## 50. Manifest requirement

File rendering SHOULD produce a JSON manifest by default.

The manifest is the machine-readable bridge between authored scripts and generated assets.

Example:

```json
{
  "elscript_version": "1.0",
  "script_id": "signal-below",
  "provider": "elevenlabs",
  "model": "eleven_v3",
  "output_mode": "single",
  "output_format": "mp3_44100_192",
  "files": [
    {
      "path": "signal-below.mp3",
      "duration_seconds": 64.123
    }
  ],
  "scenes": [],
  "timeline": [],
  "segments": []
}
```

---

## 51. Segment manifest record

Recommended information:

```json
{
  "id": "basement.mara.question",
  "scene_id": "basement",
  "ordinal": 13,
  "speaker": "MARA",
  "voice_id": "provider_voice_id",
  "model": "eleven_v3",
  "source_text": "Calypso... how far?",
  "effective_performance": {
    "emotion": "frightened",
    "intensity": 0.72,
    "pace": "slow",
    "volume": "quiet"
  },
  "file": "basement_0013_mara.mp3",
  "start_seconds": 37.418,
  "end_seconds": 39.772,
  "duration_seconds": 2.354,
  "provider_request_id": "...",
  "render_fingerprint": "..."
}
```

The manifest MUST NOT contain API secrets.

Source text inclusion SHOULD be configurable for privacy-sensitive applications.

---

## 52. Timeline events

The manifest SHOULD preserve non-speech ordered events:

```json
{
  "type": "pause",
  "duration_seconds": 1.25,
  "after_ordinal": 13
}
```

```json
{
  "type": "marker",
  "name": "chamber-reveal",
  "time_seconds": 42.51
}
```

This is particularly important in `segment` mode, where inter-segment silence is not stored in audio files.

---

## 53. Timestamps and alignment

Where provider endpoints supply timing data, retain:

- original character alignment
- normalized character alignment
- dialogue voice segments
- provider request IDs

The manifest MAY store complete alignment directly or in sidecar files if data volume is large.

For assembled outputs, provider-local timestamps must be translated to output-global timeline positions.

As of 2026-08-14, ElevenLabs timestamp endpoints expose character-level alignment, and timestamped Text-to-Dialogue responses expose voice-segment information.

---

# Part VIII — Cache and regeneration contracts

## 54. Render fingerprint

ELScript SHOULD support content-addressed render caching.

A speech/render fingerprint must include every input that can materially affect generated provider audio.

At minimum:

```text
provider
endpoint strategy where material
model
voice_id
fully compiled provider text/prompt
semantic-to-provider translation version
effective provider settings
seed
language
pronunciation configuration
normalization settings
relevant continuity context
provider adapter version when translation behavior changes
```

It MUST NOT include:

- API key
- output directory
- output filename
- unrelated metadata

---

## 55. Cache behavior

A valid cached provider result MAY be reused instead of making a chargeable request.

Cache reuse must not change observable script semantics.

If context affects generation, context must affect the fingerprint.

A cache hit should be visible in diagnostics/manifest metadata.

---

## 56. Incremental regeneration

Stable logical segment IDs plus fingerprints allow changed scripts to regenerate only affected audio.

However, continuity creates dependencies.

Changing one segment MAY invalidate neighboring segments when:

- they were generated in one dialogue request
- previous/next context was used
- request stitching was used
- provider grouping changed

The cache layer must therefore treat provider-request context as part of render identity rather than assuming every authored line is independent.

---

# Part IX — Validation, diagnostics, and errors

## 57. Validation phases

Errors should identify the phase that failed:

1. source discovery
2. YAML parsing
3. logical merge
4. schema validation
5. reference validation
6. semantic compilation
7. provider capability validation
8. provider generation
9. audio assembly
10. output writing

Whenever possible, report:

- source file
- YAML path
- scene ID
- character ID
- segment ID
- provider/model
- actionable correction

---

## 58. Error categories

Conceptual hierarchy:

```text
ELScriptError

InputError
  SourceNotFoundError
  InvalidYamlError

MergeError
  MergeConflictError

SchemaError
  ValidationError

CompileError
  UnknownCharacterError
  UnknownPresetError
  InvalidStateError

CapabilityError
  UnsupportedModelFeatureError
  UnsupportedOutputFormatError
  ProviderLimitError

ProviderError
  AuthenticationError
  RateLimitError
  GenerationError

AudioError
  DecodeError
  AssemblyError

OutputError
  FilenameCollisionError
  WriteError
```

Exact class names are implementation decisions, but callers should be able to distinguish these categories programmatically.

---

## 59. Warning policy

Warnings are appropriate for recoverable behavior such as:

- provider capability cannot be pre-verified but will be attempted
- semantic direction has no exact provider equivalent and is approximated
- scene ordering mixes explicit and implicit values
- provider tag is experimental
- deterministic seed is best-effort rather than guaranteed

Warnings MUST NOT be used to hide:

- conflicting YAML definitions
- unknown characters
- unsupported requested features that would be silently lost
- invalid credentials
- missing required voices

Warnings should have stable codes so applications can filter or escalate them.

---

# Part X — Security and privacy

## 60. API key handling

Credentials:

- come from explicit secure configuration or environment
- are never written to manifests
- are never serialized into caches
- are redacted from errors/logs
- are never included in provider prompt text

---

## 61. YAML safety

YAML parsing MUST use safe semantics.

Do not allow source YAML to instantiate arbitrary runtime objects.

Directory traversal and YAML aliases must not permit arbitrary filesystem access.

---

## 62. Output path safety

All generated paths must remain inside `output_dir`.

Scene IDs, script IDs, and character names are untrusted filename components and must be sanitized.

A script value such as:

```yaml
id: ../../outside
```

must never escape the output directory.

---

## 63. Provider logging / retention

`render.enable_logging` maps to provider history/retention behavior only where supported.

The system should explain provider limitations.

As of 2026-08-14, ElevenLabs documents `enable_logging=false` as zero-retention mode restricted to Enterprise and notes that request-history features such as request stitching are unavailable for such requests.

---

# Part XI — Extensibility

## 64. Additional providers

A future provider should be able to implement the provider contract without changing:

- folder merge behavior
- ELScript state semantics
- output naming
- manifest structure
- CLI parsing
- core script schema, except optional extension capabilities

Examples might include:

```text
OpenAI
local TTS
Kokoro
other hosted providers
```

No such provider is required by ELScript 1.0.

---

## 65. Capability-driven translation

The compiler resolves what the author wants.

The provider adapter decides how to express it.

For example:

```yaml
pace: slow
emotion: frightened
```

might become:

- audio tags for one model
- numeric speed plus style controls for another
- prompt context for another
- a warning if no equivalent exists

This is the central abstraction boundary.

---

## 66. Schema evolution

The top-level version:

```yaml
elscript: "1.0"
```

controls authoring-language compatibility.

Rules:

- backward-compatible additions increment minor version as appropriate
- breaking syntax/semantic changes require a major version
- provider API changes do not automatically require an ELScript schema change
- adapters SHOULD handle provider evolution behind the capability layer

Unknown future minor-version fields should not be silently ignored unless explicitly allowed by compatibility rules.

---

# Part XII — Complete schema example

## 67. Comprehensive example

```yaml
elscript: "1.0"

meta:
  id: signal-below
  title: "The Signal Below"
  description: "ELScript feature demonstration"
  language: en
  tags: [demo, science-fiction]

render:
  provider: elevenlabs
  mode: auto
  model: eleven_v3
  output_format: mp3_44100_192
  timestamps: true
  seed: 771943
  text_normalization: auto
  language_text_normalization: false
  enable_logging: true

  chunking:
    max_chars: 1800
    prefer_scene_boundaries: true
    prefer_utterance_boundaries: true
    preserve_continuity: true

pronunciation:

  dictionaries:
    - id: EXAMPLE_DICTIONARY_ID
      version_id: EXAMPLE_VERSION_ID

  terms:
    Calypso:
      ipa: "kəˈlɪpsoʊ"

    XJ-9:
      say_as: "X J Nine"

presets:

  narrator:
    emotion: neutral
    intensity: 0.25
    energy: 0.30
    pace: measured
    volume: normal
    delivery: [cinematic, restrained]

  human:
    emotion: neutral
    intensity: 0.40
    energy: 0.50
    pace: normal
    volume: normal

  machine:
    emotion: neutral
    intensity: 0.15
    energy: 0.30
    pace: measured
    volume: normal
    delivery: [precise, calm, understated]

characters:

  NARRATOR:
    voice_id: VOICE_NARRATOR
    preset: narrator

  ELLIS:
    voice_id: VOICE_ELLIS
    preset: human

    defaults:
      emotion: tired
      intensity: 0.35

  CALYPSO:
    voice_id: VOICE_CALYPSO
    preset: machine
    model: eleven_v3

    defaults:
      emotion: neutral
      delivery: [precise, calm]

    api:
      # Provider-specific settings may be supplied here.
      # The ElevenLabs adapter validates them against the active model.
      voice_settings: {}

scenes:

  - id: station
    order: 10
    title: "The Station"

    context: >
      Ellis is repairing an abandoned research station.
      Calypso is the station AI.

    inherit_character_state: false

    script:

      - NARRATOR: >
          At 2:17 in the morning, the station spoke for the first time
          in eleven years.

      - pause: 0.7

      - CALYPSO:
          cue: [soft inhale]
          say: >
            Ellis.

      - ELLIS:
          set:
            emotion: startled
            intensity: 0.65
            energy: 0.70
          say: >
            Jesus!

      - ELLIS:
          set:
            intensity: 0.45
          say: >
            Calypso? You said voice synthesis was offline.

      - CALYPSO: >
          It was.

      - ELLIS:
          set:
            emotion: suspicious
            pace: slow
          say: >
            Was?

      - CALYPSO:
          set:
            emotion: concerned
            intensity: 0.30

          say:
            - text: >
                I restored the subsystem because I require your attention.

            - cue: short pause

            - with:
                volume: quiet
                delivery: [carefully]
              text: >
                Immediately.

      - ELLIS:
          cue: [sighs]
          set:
            emotion: irritated
            intensity: 0.45
          say: >
            It's two in the morning.

      - CALYPSO: >
          Two seventeen.

      - ELLIS:
          tags: [sarcastic]
          say: >
            Thank you, Calypso.

      - CALYPSO:
          with:
            emotion: curious
          say: >
            Was that sarcasm?

      - ELLIS: >
          Yes.

      - CALYPSO: >
          Understood.

      - pause: 0.4

      - CALYPSO:
          set:
            emotion: concerned
            intensity: 0.50
          say: >
            The seismic array has detected a repeating signal.

      - ELLIS:
          reset: pace
          set:
            emotion: confused
          say: >
            A seismic signal?

      - CALYPSO: >
          No.

      - CALYPSO:
          set:
            intensity: 0.65
          say:
            - text: >
                A radio signal.

            - cue: long pause

            - with:
                volume: quiet
              text: >
                From beneath the station.

      - pause: 1.0

      - ELLIS:
          set:
            emotion: uneasy
            intensity: 0.60
            pace: slow
          say: >
            That's impossible.

      - CALYPSO:
          with:
            delivery: [very gently]
          say: >
            I know.

      - ELLIS:
          say:
            - text: >
                How far beneath us?

            - set:
                emotion: frightened
                intensity: 0.72

            - cue: nervous breath

            - with:
                volume: quiet
              text: >
                Calypso... how far?

      - CALYPSO:
          set:
            emotion: apprehensive
            intensity: 0.55
          say: >
            Four meters.

      - marker: reveal

      - pause: 1.4

      - NARRATOR:
          set:
            emotion: ominous
            intensity: 0.50
          say: >
            Ellis looked down at the concrete floor.

      - ELLIS:
          with:
            volume: whisper
          say: >
            There's no basement.

      - CALYPSO:
          cue: [softly]
          say: >
            I am aware.

      - note: >
          End of demonstration scene.

export:
  mode: single
  normalize_loudness: false

  manifest:
    enabled: true
    include_source_text: true

  metadata:
    save_request_ids: true
    save_voice_segments: true
    save_character_timestamps: true
    save_normalized_timestamps: true
```

---

# Part XIII — Multi-file example

## 68. Project layout

```text
signal-below/
├── meta.yaml
├── render.yaml
├── pronunciation.yaml
├── presets.yaml
├── characters/
│   ├── narrator.yaml
│   ├── ellis.yaml
│   └── calypso.yaml
└── scenes/
    ├── 010_station.yaml
    └── 020_basement.yaml
```

`meta.yaml`:

```yaml
elscript: "1.0"

meta:
  id: signal-below
  title: "The Signal Below"
  language: en
```

`render.yaml`:

```yaml
render:
  provider: elevenlabs
  model: eleven_v3
  output_format: mp3_44100_192
  timestamps: true
```

`characters/calypso.yaml`:

```yaml
characters:
  CALYPSO:
    voice_id: VOICE_CALYPSO
    preset: machine
```

`characters/calypso-performance.yaml` could legally add:

```yaml
characters:
  CALYPSO:
    defaults:
      emotion: neutral
      delivery: [precise, calm]
```

because the two mappings do not conflict.

If it instead defines a different `voice_id`, merge fails.

`scenes/010_station.yaml`:

```yaml
scenes:
  - id: station
    order: 10
    script:
      - CALYPSO: "Ellis."
```

All files are parsed independently, logically merged, and then processed exactly like one complete YAML document.

---

# Part XIV — Expected public results

## 69. `RenderResult`

File rendering should return structured result data.

Conceptual fields:

```python
RenderResult(
    files=[...],
    manifest_path=...,
    duration_seconds=...,
    scenes=[...],
    segments=[...],
    provider_requests=...,
    warnings=[...],
)
```

Callers should not need to parse the manifest file just to discover generated paths.

---

## 70. `AudioChunk`

Streaming should expose structured metadata.

Conceptual fields:

```python
AudioChunk(
    data=b"...",
    format="mp3_44100_128",
    scene_id="station",
    segment_id="station.calypso.0002",
    ordinal=2,
    speaker="CALYPSO",
    final_for_segment=False,
    event=None,
)
```

An event-only chunk MAY have empty audio:

```python
AudioChunk(
    data=b"",
    event="marker",
    ...
)
```

or the API may define a companion event type. The exact class hierarchy is not prescribed, only the information contract.

---

# Part XV — Out of scope for ELScript 1.0

Unless later added explicitly, the following are not required baseline features:

- music generation
- environmental sound-track composition
- DAW-style multitrack editing
- automatic character voice design
- voice cloning workflows
- speech-to-speech acting transfer
- automatic LLM rewriting of dialogue
- automatic translation
- live microphone conversation management
- persistent remote asset storage
- GUI authoring

Provider tags that happen to generate sounds do not turn ELScript into a general audio-production language.

---

# Part XVI — ElevenLabs reference assumptions

The design deliberately keeps these behind a capability layer because provider behavior can change.

Official references reviewed for this baseline:

- Text-to-Speech: https://elevenlabs.io/docs/api-reference/text-to-speech/convert
- Text-to-Speech with timestamps: https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps
- Streaming TTS: https://elevenlabs.io/docs/api-reference/streaming
- Text-to-Dialogue: https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert
- Streaming dialogue with timestamps: https://elevenlabs.io/docs/api-reference/text-to-dialogue/stream-with-timestamps
- TTS best practices / Eleven v3 prompting: https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices
- Models API: https://elevenlabs.io/docs/api-reference/models/list
- Voice settings: https://elevenlabs.io/docs/api-reference/voices/settings/update

These references are implementation inputs, not frozen ELScript semantics. The provider adapter should be updated when ElevenLabs changes while preserving this document's higher-level contracts wherever practical.
