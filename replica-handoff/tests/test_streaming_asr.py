"""Sprint 2 requirement 5: interim transcripts grow incrementally; a final
transcript is only produced once, on finalize().

Async protocol (Sprint 2B, ADR-044): SimulatedASRProvider's feed_audio()/
poll_events()/finalize()/close() are all coroutines now, matching what a real
streaming provider (Deepgram) needs. No pytest-asyncio plugin is installed/needed —
these tests drive the coroutines directly via asyncio.run(), keeping the test suite
dependency-free.
"""
import asyncio

from app.streaming.asr import PLACEHOLDER_TEXT, SimulatedASRProvider


def run(coro):
    return asyncio.run(coro)


async def _feed_and_get_interim(handle, *, is_speaking=True, payload=b''):
    await handle.feed_audio(payload, is_speaking=is_speaking)
    events = await handle.poll_events()
    return events[-1] if events else None


def test_interim_events_grow_word_by_word_while_speaking():
    provider = SimulatedASRProvider(script={'inbound': ['Wir haben bereits einen Anbieter']})
    handle = run(provider.start_stream(track='inbound'))
    texts = [run(_feed_and_get_interim(handle)).text for _ in range(6)]
    assert texts == [
        'Wir', 'Wir haben', 'Wir haben bereits', 'Wir haben bereits einen',
        'Wir haben bereits einen Anbieter', 'Wir haben bereits einen Anbieter',
    ]
    assert all(e for e in texts)


def test_no_interim_event_while_silent():
    provider = SimulatedASRProvider(script={'inbound': ['hallo']})
    handle = run(provider.start_stream(track='inbound'))
    assert run(_feed_and_get_interim(handle, is_speaking=False)) is None


def test_finalize_returns_full_text_once_and_none_afterward():
    provider = SimulatedASRProvider(script={'inbound': ['Wir haben bereits einen Anbieter']})
    handle = run(provider.start_stream(track='inbound'))
    run(handle.feed_audio(b'', is_speaking=True))
    run(handle.feed_audio(b'', is_speaking=True))
    final = run(handle.finalize())
    assert final is not None
    assert final.text == 'Wir haben bereits einen Anbieter'
    assert final.kind == 'final'
    assert run(handle.finalize()) is None  # nothing in progress anymore


def test_second_utterance_on_same_track_consumes_next_script_line():
    provider = SimulatedASRProvider(script={'inbound': ['erste Aussage', 'zweite Aussage']})
    handle = run(provider.start_stream(track='inbound'))
    run(handle.feed_audio(b'', is_speaking=True))
    first = run(handle.finalize())
    run(handle.feed_audio(b'', is_speaking=True))
    second = run(handle.finalize())
    assert first.text == 'erste Aussage'
    assert second.text == 'zweite Aussage'


def test_unscripted_track_produces_obviously_fake_placeholder_not_a_plausible_transcript():
    provider = SimulatedASRProvider()  # no script at all
    handle = run(provider.start_stream(track='inbound'))
    run(handle.feed_audio(b'', is_speaking=True))
    final = run(handle.finalize())
    assert final.text == PLACEHOLDER_TEXT
    assert 'unavailable' in final.text.lower()


def test_tracks_are_independent_streams():
    provider = SimulatedASRProvider(script={'inbound': ['prospect text'], 'outbound': ['seller text']})
    inbound_handle = run(provider.start_stream(track='inbound'))
    outbound_handle = run(provider.start_stream(track='outbound'))
    run(inbound_handle.feed_audio(b'', is_speaking=True))
    run(outbound_handle.feed_audio(b'', is_speaking=True))
    assert run(inbound_handle.finalize()).text == 'prospect text'
    assert run(outbound_handle.finalize()).text == 'seller text'


def test_close_is_a_no_op_for_simulated_provider():
    provider = SimulatedASRProvider()
    handle = run(provider.start_stream(track='inbound'))
    run(handle.close())  # must not raise
