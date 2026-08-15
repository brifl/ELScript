# Streaming API

ELScript exposes synchronous `stream()` and asynchronous `astream()` Python APIs.
Streaming shares loading, validation, configuration, compilation, capability checks,
and request planning with file rendering, but writes no audio, manifest, or cache files.

## Synchronous use

```python
from elscript import stream

for chunk in stream(source="story.yaml"):
    if chunk.data:
        play(chunk.data, format=chunk.format)
    elif chunk.event == "marker":
        on_marker(chunk.metadata["name"])
```

Iteration is demand-driven: the next provider chunk is not requested until the consumer
asks for it. Closing the iterator closes the active provider stream.

## Asynchronous use

```python
from elscript import astream

async for chunk in astream(source="story.yaml"):
    if chunk.data:
        await play(chunk.data, format=chunk.format)
```

`astream()` adapts the synchronous provider iterator without blocking the event loop.
Cancellation waits for active read cleanup and closes the iterator. Cancellation
exceptions are not relabeled as provider failures.

## `AudioChunk`

Audio chunks expose:

- `data` and `format`;
- `scene_id`, `segment_id`, `ordinal`, and `speaker`;
- `final_for_segment` for the final provider piece of one logical segment;
- `event` plus `metadata` for non-audio timeline events;
- provider request/alignment metadata when returned.

An event chunk intentionally has empty `data`. Speech chunks always identify their
logical authored segment.

## Events and pauses

Pauses, markers, and notes remain ordered with speech. They are event chunks rather
than locally encoded silence:

- pause metadata includes `duration_seconds`;
- marker metadata includes `name`;
- note metadata includes `text` only when source-text inclusion is enabled.

The consumer decides how to schedule event-only chunks.

## Speech and dialogue strategy

In `auto` mode, independently attributable speech requests stream immediately. Explicit
`dialogue` mode may buffer one provider request so voice-segment timestamps can split
the response back into authored logical segments. This preserves correct attribution at
the cost of request-level latency.

## Failure behavior

Provider, decode, and attribution failures use the same stable phase/code diagnostics as
file rendering and include available provider/request/scene/segment/character context.
Ordinary unexpected adapter exceptions are normalized without exposing their messages;
`KeyboardInterrupt` and async cancellation continue to propagate.

Streaming is Python-only. The CLI has no streaming flag.
