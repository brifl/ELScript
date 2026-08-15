# Providers and capability behavior

ELScript keeps portable authoring semantics separate from provider request mechanics.
The active adapter must either honor required intent, reject it before generation, or
emit a stable warning for a documented recoverable approximation.

## Portable semantics

Prefer ELScript fields such as `emotion`, `intensity`, `energy`, `pace`, `volume`,
`delivery`, `accent`, `cue`, pronunciation terms, and explicit pauses. These express
author intent without embedding provider syntax in dialogue.

The `api` mapping is an intentional provider escape hatch. It participates in cache
identity, is validated against the selected endpoint, and may make a script non-portable.
Credentials are forbidden in `api`.

## Built-in providers

### `fake`

The fake provider is deterministic, no-network, and intended for tests, examples, CI,
and integration development. It emits valid audio/timing data and supports all current
planner features. It is not a production voice synthesizer.

### `elevenlabs`

The ElevenLabs adapter supports speech and Eleven v3 dialogue, timestamped and streaming
operations, native v3 IPA, pronunciation-dictionary locators, seed, normalization,
request logging control, speech voice settings, request stitching, and dialogue voice
segments where the selected operation supports them.

Current built-in guardrails (reviewed 2026-08-14):

- dialogue uses `eleven_v3`;
- dialogue requests are kept at or below 2,000 characters for reliable generation;
- timestamped dialogue retains `voice_segments` for authored attribution;
- an individual dialogue request uses at most 10 unique voices;
- no more than three pronunciation dictionary locators are attached to one request;
- seeded provider output is best-effort, not byte-deterministic;
- zero-retention mode cannot use request stitching;
- account tier may restrict formats, zero retention, quotas, or endpoint access.

Before release, verify these assumptions against the current
[Text-to-Dialogue timestamp stream](https://elevenlabs.io/docs/api-reference/text-to-dialogue/stream-with-timestamps),
[models](https://elevenlabs.io/docs/overview/models), and
[TTS best practices](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices).

## Semantic translation and warnings

The current ElevenLabs translation version is part of render/cache identity. Expressive
directions require `eleven_v3`; ELScript converts portable state into validated v3
prompt tags. Some mappings are approximations and emit codes such as intensity/energy
approximation, experimental semantic tags, IPA alias fallback, unverified language
normalization, and best-effort seed behavior.

Warnings never hide conflicting definitions, unknown references, credentials, missing
voices, or unsupported required intent. See [Troubleshooting](troubleshooting.md) for the
full stable code list.

## Out of scope for ELScript 1.0

ELScript 1.0 does not provide music or environmental-track generation, DAW-style
multitrack editing, voice design/cloning workflows, speech-to-speech acting transfer,
LLM rewriting, automatic translation, live microphone conversation management,
persistent remote asset storage, or a GUI authoring environment.

Provider audio tags that happen to create non-speech sounds do not turn ELScript into a
general audio-production language.
