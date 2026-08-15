# ELScript 1.0 syntax

ELScript is a strict YAML document format for authored speech, performance state, and
ordered timeline events. The canonical version marker is:

```yaml
elscript: "1.0"
```

Unknown fields are rejected. YAML is loaded with safe semantics; Python object tags and
recursive aliases are not supported.

## Document shape

```yaml
elscript: "1.0"

meta:
  id: story-id
  title: "Optional title"
  language: en

render:
  provider: elevenlabs
  mode: auto
  model: eleven_v3
  output_format: mp3_44100_128
  timestamps: true

presets: {}
characters: {}
pronunciation: {}
scenes: []

export:
  mode: single
  normalize_loudness: false
```

Only `elscript`, `characters`, and `scenes` are required. If `meta.id` is omitted,
ELScript derives a stable script ID from the source.

## Characters and presets

Character IDs are author-facing speaker names. They are distinct from provider voice
IDs.

```yaml
presets:
  narration:
    emotion: neutral
    intensity: 0.25
    pace: measured

characters:
  NARRATOR:
    voice_id: provider-voice-id
    preset: narration
    model: eleven_v3
    language: en
    defaults:
      delivery: [warm, restrained]
```

The portable performance fields are `emotion`, `intensity`, `energy`, `pace`,
`volume`, `delivery`, and `accent`. Intensity and energy are finite numbers from `0.0`
through `1.0`.

## Scenes and timeline events

Scenes contain one-key script entries:

```yaml
scenes:
  - id: arrival
    order: 10
    title: "Arrival"
    context: "A dark station after midnight."
    script:
      - NARRATOR: "Mara opened the door."
      - pause: 0.5
      - marker: door-open
      - note: "Not sent to the provider."
```

`order` controls scene ordering. When it is absent, deterministic source order is the
fallback. `pause`, `marker`, and `note` are reserved event names and cannot be character
IDs.

## Persistent and temporary state

`set` changes a character's state for later speech in the scene:

```yaml
- MARA:
    set:
      emotion: afraid
      intensity: 0.7
    say: "Did you hear that?"
```

`with` changes only the speech in the same entry:

```yaml
- MARA:
    with:
      volume: whisper
    say: "Do not move."
```

`reset` restores one or more fields to the character baseline:

```yaml
- MARA:
    reset: [emotion, intensity]
    say: "It was only the wind."
```

Use `reset: all` to restore every field. Character state resets at each scene unless
`inherit_character_state: true` is set on the next scene.

## Structured speech

A `say` list can create multiple logical speech segments and state transitions inside
one authored entry:

```yaml
- MARA:
    id: reunion
    say:
      - text: "I thought you had left."
      - cue: exhales
      - set:
          emotion: relieved
      - text: "But you came back."
      - with:
          delivery: [laughing through tears]
        text: "You actually came back."
```

Explicit `id` values must be unique. Generated IDs remain stable for unchanged source
structure.

## Pronunciation

```yaml
pronunciation:
  dictionaries:
    - id: provider-dictionary-id
      version_id: provider-version-id
  terms:
    Calypso:
      ipa: "kəˈlɪpsoʊ"
    XJ-9:
      say_as: "X J Nine"
```

The active provider decides whether a term uses native IPA or a validated alias. An
unsupported required mechanism is an error; a recoverable approximation emits a coded
warning.

## Output modes

`export.mode` is one of:

- `single`: one file for the complete timeline;
- `scene`: one file per scene;
- `segment`: one file per speech segment, with pauses/events retained in the manifest.

Generated components are sanitized and contained inside `output_dir`; existing files
are never overwritten.

## Multi-file projects

A directory source may split top-level fields across any `.yaml` and `.yml` files.
Each file is parsed independently and then logically merged. Compatible mappings merge,
scenes append and sort deterministically, and conflicting scalar definitions fail.

See the tested [single-file](../tests/fixtures/signal_below.yaml) and
[multi-file](../tests/fixtures/signal_below/) comprehensive examples.

## Provider escape hatch

An `api` mapping may appear at render, preset, character, scene, utterance, and
structured-segment scopes. It is provider-specific, participates in render identity,
and is validated by the selected adapter. Credentials are forbidden in every `api`
mapping.

Portable semantics should use the fields above. Use `api` only when provider lock-in is
intentional; see [Providers](providers.md).
