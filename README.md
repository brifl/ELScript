# ELScript

ELScript is a Python library and command-line tool for rendering structured, expressive, multi-character scripts to speech with ElevenLabs.

> **Release status:** `0.1.0a0` is an alpha release. The ELScript 1.0 document
> format is implemented and tested, but provider behavior and the Python API may still
> change before `1.0.0`.

It is designed for:

- robot voices and interactive characters
- game dialogue
- story narration
- multi-character audio stories
- scripted voice acting
- reusable character voice libraries

The project uses a readable YAML script format that separates **what a character should sound like** from **how the speech provider implements that performance**. Character performance state is persistent: if a character becomes frightened, angry, quiet, or slow, that state remains active through later exchanges until the script changes or resets it.

ELScript can render a single YAML file, logically merge a directory of YAML files into one script, or render YAML supplied directly by Python code.

## Core features

- Multi-character scripts with persistent emotional and delivery state
- Mid-line emotional and performance changes
- Reusable performance presets
- Eleven v3 audio tags and raw provider escape hatches
- Pronunciation control, including v3 IPA and ElevenLabs pronunciation dictionaries
- Single-file, per-scene, or per-segment audio output
- Python streaming API for interactive applications
- Deterministic logical merging of multi-file projects
- Layered configuration from library defaults, `.env`, YAML, and call/CLI overrides
- Provider capability validation so unsupported settings are reported instead of silently ignored
- Timestamp and speaker metadata where supported by the provider
- Render manifests for games, animation, subtitles, and downstream tooling
- Architecture intended to support additional speech providers without changing the script language

## Installation

ELScript requires Python 3.11 or newer. Install the package from PyPI:

```bash
pip install elscript
```

```python
import elscript
```

```bash
elscript story.yaml
```

For development from a source checkout:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

## ElevenLabs configuration

Set the API key in `.env`:

```dotenv
ELEVENLABS_API_KEY=your_api_key_here
```

Common defaults may also be placed in `.env`:

```dotenv
ELSCRIPT_PROVIDER=elevenlabs
ELSCRIPT_MODEL=eleven_v3
ELSCRIPT_OUTPUT_FORMAT=mp3_44100_192
ELSCRIPT_OUTPUT_MODE=single
ELSCRIPT_TEXT_NORMALIZATION=auto
ELSCRIPT_ENABLE_LOGGING=true
```

Credentials must be supplied through the process environment or a discovered/explicit
`.env` file, never through script YAML or an `api` mapping. See
[Configuration](docs/configuration.md) for discovery and precedence rules.

## Quick start

Create `story.yaml`:

<!-- test:quick-start-yaml -->
```yaml
elscript: "1.0"

meta:
  id: first-story
  title: "First Story"
  language: en

render:
  provider: elevenlabs
  model: eleven_v3
  output_format: mp3_44100_192

characters:
  NARRATOR:
    voice_id: YOUR_NARRATOR_VOICE_ID
    preset: narration

  MARA:
    voice_id: YOUR_MARA_VOICE_ID
    defaults:
      emotion: confident
      intensity: 0.4
      pace: normal

presets:
  narration:
    emotion: neutral
    intensity: 0.25
    pace: measured
    delivery: [warm, restrained]

scenes:
  - id: arrival
    script:
      - NARRATOR: >
          Mara reached the station just before midnight.

      - MARA:
          set:
            emotion: uneasy
            intensity: 0.55
          say: >
            Hello? Is anyone here?

      - pause: 0.8

      - MARA:
          with:
            volume: whisper
          say: >
            I really don't like this.
```
<!-- /test:quick-start-yaml -->

Render it:

```bash
elscript story.yaml --output ./audio
```

The default output mode produces one audio file:

```text
audio/
├── first-story.mp3
└── first-story.manifest.json
```

The quick-start render makes a real ElevenLabs request and may incur provider charges.
The test suite executes the same YAML through ELScript's deterministic no-network fake
provider.

## Comprehensive examples

The repository includes the complete **The Signal Below** example in both supported
project layouts:

- [single YAML file](tests/fixtures/signal_below.yaml)
- [multi-file directory](tests/fixtures/signal_below/)

Documentation tests render both forms through the canonical pipeline and verify their
audio and manifests are equivalent.

## Python API

### Render a file

```python
from elscript import render

result = render(
    source="story.yaml",
    output_dir="./audio",
)
```

### Render a directory

```python
result = render(
    source="./story",
    output_dir="./audio",
)
```

All `.yaml` and `.yml` files under the directory are parsed separately and logically merged into one ELScript document. Files are **not** concatenated as text.

### Render YAML directly

```python
from elscript import render_yaml

script = """
elscript: "1.0"

characters:
  ORION:
    voice_id: YOUR_VOICE_ID

scenes:
  - id: hello
    script:
      - ORION: "Systems online."
"""

result = render_yaml(
    script,
    output_dir="./audio",
)
```

### Render a parsed Python mapping

```python
from elscript import render_document

result = render_document(
    {
        "elscript": "1.0",
        "characters": {
            "ORION": {
                "voice_id": "YOUR_VOICE_ID",
            }
        },
        "scenes": [
            {
                "id": "hello",
                "script": [
                    {"ORION": "Systems online."}
                ],
            }
        ],
    },
    output_dir="./audio",
)
```

All public convenience functions use the same loading, validation, compilation, rendering, and output pipeline.

## Configuration precedence

Effective render configuration is resolved in this order, highest priority first:

```text
Python call arguments / CLI arguments
        ↓
YAML render and export configuration
        ↓
process environment
        ↓
.env
        ↓
library defaults
```

Only values that are explicitly supplied at a higher layer override lower layers.

Example:

```dotenv
ELSCRIPT_OUTPUT_FORMAT=mp3_44100_128
```

```yaml
render:
  output_format: mp3_44100_192
```

```python
render(
    source="story.yaml",
    output_dir="./audio",
    options={"output_format": "pcm_44100"},
)
```

The Python value wins.

Provider adapters must validate whether a selected model/account supports the resulting options.

## Multi-file projects

A larger project can be organized however is convenient:

```text
story/
├── meta.yaml
├── render.yaml
├── presets.yaml
├── characters/
│   ├── narrator.yaml
│   ├── mara.yaml
│   └── orion.yaml
└── scenes/
    ├── 010_arrival.yaml
    ├── 020_restaurant.yaml
    └── 030_basement.yaml
```

Example character file:

```yaml
characters:
  MARA:
    voice_id: YOUR_MARA_VOICE_ID
    defaults:
      emotion: neutral
      intensity: 0.4
```

Example scene file:

```yaml
scenes:
  - id: restaurant
    order: 20
    script:
      - MARA: "Table for two, please."
```

The directory loader recursively parses YAML files, merges compatible mapping sections, appends scenes, rejects conflicting definitions, and then validates the resulting logical document.

Scene order is determined by explicit `order` values when present, with deterministic source order as the fallback.

## Persistent performance state

A character's current performance state is sticky within a scene.

```yaml
- MARA:
    set:
      emotion: angry
      intensity: 0.8
    say: "You lied to me."

- ORION: "I withheld information."

- MARA:
    set:
      intensity: 0.4
    say: "I think I understand why."
```

Mara remains `angry` through the exchange. Only `intensity` changes from `0.8` to `0.4`.

### Temporary override

Use `with` when the change applies only to one utterance:

```yaml
- MARA:
    with:
      volume: whisper
    say: "Don't move."
```

After the utterance, her previous volume state is restored.

### Reset

```yaml
- MARA:
    reset: [emotion, intensity]
    say: "All right."
```

Or reset all character state:

```yaml
- MARA:
    reset: all
    say: "Let's start over."
```

## Mid-line acting

A `say` value may contain multiple segments and state changes:

```yaml
- MARA:
    say:
      - text: "I thought you'd left."

      - cue: exhales

      - set:
          emotion: relieved
          intensity: 0.7

      - text: "But you came back."

      - with:
          delivery: [laughing through tears]
        text: "You actually came back."
```

`set` persists from that point forward. `with` applies only to the segment where it appears.

## Explicit Eleven v3 tags

Semantic performance instructions are preferred because they keep scripts provider-independent:

```yaml
- MARA:
    set:
      emotion: suspicious
      pace: slow
    say: "That doesn't make sense."
```

When exact Eleven v3 prompting is desired, raw tags are available:

```yaml
- MARA:
    tags: [sarcastic, exhales]
    say: "Wonderful."
```

Provider-specific settings may also be supplied through an `api` escape hatch. Unsupported options must generate validation errors or explicit warnings rather than being silently discarded.

## Pronunciation

Script-level pronunciation aliases keep phonetic markup out of dialogue:

```yaml
pronunciation:
  terms:
    Calypso:
      ipa: "kəˈlɪpsoʊ"

    XJ-9:
      say_as: "X J Nine"
```

The renderer chooses the appropriate provider/model mechanism. For Eleven v3, IPA can be compiled into v3's native `/IPA/` form. Existing ElevenLabs pronunciation dictionaries may also be referenced.

## Output modes

### Single file — default

```bash
elscript story.yaml --output ./audio --mode single
```

```text
audio/
├── first-story.mp3
└── first-story.manifest.json
```

### One file per scene

```bash
elscript story.yaml --output ./audio --mode scene
```

```text
audio/
├── arrival.mp3
├── restaurant.mp3
├── basement.mp3
└── first-story.manifest.json
```

### One file per speech segment

```bash
elscript story.yaml --output ./audio --mode segment
```

```text
audio/
├── arrival_0001_narrator.mp3
├── arrival_0002_mara.mp3
├── restaurant_0003_mara.mp3
├── restaurant_0004_allen.mp3
└── first-story.manifest.json
```

The sortable number is a zero-padded global speech-segment ordinal. Scene IDs and speaker names are sanitized only as needed for safe filenames.

Explicit script pauses are represented in the manifest in segment mode rather than being emitted as standalone silent files.

## Streaming

Streaming is a Python-library feature, not a CLI feature.

Synchronous:

```python
from elscript import stream

for chunk in stream(yaml_text=script):
    if chunk.data:
        audio_device.write(chunk.data)
    elif chunk.event == "marker":
        handle_marker(chunk.metadata["name"])
```

Asynchronous:

```python
from elscript import astream

async for chunk in astream(yaml_text=script):
    if chunk.data:
        await audio_device.write(chunk.data)
```

Chunks contain audio bytes plus structured metadata such as the current scene, speech segment, speaker, and segment completion state. This supports robots and interactive applications without forcing them to reverse-engineer the audio stream.

The CLI intentionally does not expose a streaming mode.

## Render manifest

File rendering produces a machine-readable manifest by default.

Typical information includes:

```json
{
  "manifest_version": "1.0",
  "script_id": "first-story",
  "provider": "elevenlabs",
  "models": ["eleven_v3"],
  "output_mode": "single",
  "output_format": "mp3_44100_192",
  "segments": [
    {
      "id": "arrival.0001",
      "scene_id": "arrival",
      "ordinal": 1,
      "speaker": "NARRATOR",
      "start_seconds": 0.0,
      "end_seconds": 3.84
    }
  ]
}
```

When available from the provider, character timing, normalized timing, request IDs, and voice-segment metadata can also be retained.

This makes the render output useful for:

- subtitles
- game dialogue systems
- robot mouth animation
- lip sync
- scene triggers
- regeneration
- debugging
- cost-aware caching

## CLI

Basic use:

```bash
elscript story.yaml
```

Specify an output directory:

```bash
elscript story.yaml --output ./build/audio
```

Render a directory:

```bash
elscript ./story --output ./build/audio
```

Select output mode:

```bash
elscript ./story --output ./build/audio --mode scene
```

Override render settings:

```bash
elscript ./story \
  --output ./build/audio \
  --model eleven_v3 \
  --format mp3_44100_192 \
  --seed 12345
```

The CLI is a thin wrapper around the Python API and must not have separate script interpretation or rendering behavior.

## Documentation

- [ELScript 1.0 syntax](docs/syntax.md)
- [Configuration and security](docs/configuration.md)
- [Manifest contract](docs/manifest.md)
- [Streaming API](docs/streaming.md)
- [Providers and capability behavior](docs/providers.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Release checklist](docs/releasing.md)

## Design document

See [`DESIGN.md`](DESIGN.md) for the authoritative contracts covering:

- source loading and logical merge behavior
- full ELScript schema
- state inheritance and reset semantics
- render configuration precedence
- provider capability negotiation
- ElevenLabs mapping
- render planning and continuity
- streaming behavior
- output naming
- manifests and timestamps
- errors and warnings
- caching identity
- security and extensibility
