from __future__ import annotations

import asyncio
import time
from pathlib import Path
from threading import Event

import pytest

import elscript.api as api_module
from elscript import astream, render_document, stream
from elscript.audio import decode_audio
from elscript.providers.base import (
    GenerationChunk,
    ProviderCapabilities,
    ProviderRequest,
)
from elscript.providers.fake import fake_capabilities

FIXTURES = (Path(__file__).parent / "fixtures").resolve()
SIGNAL_PROJECT = FIXTURES / "signal_below"


def _document(
    script: list[dict[str, object]],
    *,
    mode: str = "auto",
    chunking_max: int = 1_800,
) -> dict[str, object]:
    return {
        "elscript": "1.0",
        "meta": {"id": "stream-story"},
        "render": {
            "provider": "fake",
            "mode": mode,
            "output_format": "wav_16000",
            "timestamps": True,
            "chunking": {"max_chars": chunking_max},
        },
        "characters": {
            "MARA": {"voice_id": "mara-voice"},
            "ORION": {"voice_id": "orion-voice"},
        },
        "scenes": [{"id": "one", "script": script}],
    }


def test_stream_preserves_authored_events_and_attributes_every_audio_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    chunks = tuple(stream(source=SIGNAL_PROJECT.resolve()))

    assert len(chunks) == 36
    speech = [chunk for chunk in chunks if chunk.data]
    events = [chunk for chunk in chunks if chunk.event]
    assert len(speech) == 30
    assert [chunk.event for chunk in events] == [
        "pause",
        "pause",
        "pause",
        "marker",
        "pause",
        "note",
    ]
    assert all(
        chunk.scene_id == "station"
        and chunk.segment_id is not None
        and chunk.ordinal is not None
        and chunk.speaker is not None
        and chunk.final_for_segment
        for chunk in speech
    )
    assert [chunk.ordinal for chunk in speech] == list(range(1, 31))
    assert all(
        decode_audio(chunk.data, chunk.format).duration_seconds
        == pytest.approx(0.1, abs=1 / 16_000)
        for chunk in speech
    )
    marker = next(chunk for chunk in events if chunk.event == "marker")
    assert marker.metadata == {"after_ordinal": 27, "name": "reveal"}
    assert not tuple(tmp_path.iterdir())


def test_split_logical_segment_marks_only_the_last_request_as_final() -> None:
    chunks = tuple(
        stream(
            document=_document(
                [{"MARA": "ABCDEFGHIJ"}],
                mode="speech",
                chunking_max=4,
            )
        )
    )

    assert len(chunks) == 3
    assert len({chunk.segment_id for chunk in chunks}) == 1
    assert [chunk.final_for_segment for chunk in chunks] == [False, False, True]
    assert [chunk.metadata["render_request_id"] for chunk in chunks] == [
        "request.0001",
        "request.0002",
        "request.0003",
    ]


def test_explicit_dialogue_stream_is_split_into_attributed_valid_audio() -> None:
    chunks = tuple(
        stream(
            document=_document(
                [{"MARA": "One"}, {"ORION": "Two"}],
                mode="dialogue",
            )
        )
    )

    assert [(chunk.ordinal, chunk.speaker) for chunk in chunks] == [
        (1, "MARA"),
        (2, "ORION"),
    ]
    assert all(chunk.final_for_segment for chunk in chunks)
    assert [chunk.metadata["dialogue_input_index"] for chunk in chunks] == [0, 1]
    assert [
        decode_audio(chunk.data, chunk.format).duration_seconds for chunk in chunks
    ] == pytest.approx([0.1, 0.1], abs=1 / 16_000)


def test_sync_iteration_applies_exact_consumer_backpressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountingProvider:
        provider_id = "fake"

        def __init__(self) -> None:
            self.pulls = 0
            self.closed = 0

        def describe_capabilities(self) -> ProviderCapabilities:
            return fake_capabilities()

        def stream(self, request: ProviderRequest):  # type: ignore[no-untyped-def]
            try:
                for index in range(3):
                    self.pulls += 1
                    yield GenerationChunk(
                        audio=f"chunk-{index}".encode(),
                        output_format=request.output_format,
                        final=index == 2,
                    )
            finally:
                self.closed += 1

    provider = CountingProvider()
    monkeypatch.setattr(api_module, "FakeProvider", lambda: provider)
    iterator = stream(document=_document([{"MARA": "One"}], mode="speech"))

    assert provider.pulls == 0
    assert next(iterator).data == b"chunk-0"
    assert provider.pulls == 1
    assert next(iterator).data == b"chunk-1"
    assert provider.pulls == 2
    iterator.close()  # type: ignore[attr-defined]
    assert provider.pulls == 2
    assert provider.closed == 1


def test_async_stream_matches_sync_order_and_metadata() -> None:
    document = _document(
        [
            {"MARA": "One"},
            {"pause": 0.25},
            {"marker": "beat"},
            {"ORION": "Two"},
        ]
    )
    expected = tuple(stream(document=document))

    async def collect():  # type: ignore[no-untyped-def]
        return tuple([chunk async for chunk in astream(document=document)])

    actual = asyncio.run(collect())

    assert actual == expected


def test_async_cancellation_closes_active_iterator_and_later_render_is_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowProvider:
        provider_id = "fake"

        def __init__(self) -> None:
            self.first = Event()
            self.closed = False

        def describe_capabilities(self) -> ProviderCapabilities:
            return fake_capabilities()

        def stream(self, request: ProviderRequest):  # type: ignore[no-untyped-def]
            try:
                yield GenerationChunk(
                    audio=b"first",
                    output_format=request.output_format,
                    final=False,
                )
                self.first.set()
                time.sleep(0.05)
                yield GenerationChunk(
                    audio=b"second",
                    output_format=request.output_format,
                    final=True,
                )
            finally:
                self.closed = True

    provider = SlowProvider()
    monkeypatch.setattr(api_module, "FakeProvider", lambda: provider)
    document = _document([{"MARA": "One"}], mode="speech")

    async def cancel_during_next() -> None:
        async def consume() -> None:
            async for _ in astream(document=document):
                await asyncio.sleep(0)

        task = asyncio.create_task(consume())
        await asyncio.to_thread(provider.first.wait)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_during_next())

    assert provider.closed
    monkeypatch.undo()
    later = render_document(document, output_dir=tmp_path / "later")
    assert later.files[0].is_file()
