"""Sprint 2 requirement 5: interim transcripts grow incrementally; a final
transcript is only produced once, on finalize()."""
from app.streaming.asr import PLACEHOLDER_TEXT, SimulatedASRProvider


def test_interim_events_grow_word_by_word_while_speaking():
    provider = SimulatedASRProvider(script={'inbound': ['Wir haben bereits einen Anbieter']})
    handle = provider.start_stream(track='inbound')
    texts = []
    for _ in range(6):
        event = handle.feed_audio(b'', is_speaking=True)
        texts.append(event.text)
    assert texts == [
        'Wir', 'Wir haben', 'Wir haben bereits', 'Wir haben bereits einen',
        'Wir haben bereits einen Anbieter', 'Wir haben bereits einen Anbieter',
    ]
    assert all(e for e in texts)


def test_no_interim_event_while_silent():
    provider = SimulatedASRProvider(script={'inbound': ['hallo']})
    handle = provider.start_stream(track='inbound')
    assert handle.feed_audio(b'', is_speaking=False) is None


def test_finalize_returns_full_text_once_and_none_afterward():
    provider = SimulatedASRProvider(script={'inbound': ['Wir haben bereits einen Anbieter']})
    handle = provider.start_stream(track='inbound')
    handle.feed_audio(b'', is_speaking=True)
    handle.feed_audio(b'', is_speaking=True)
    final = handle.finalize()
    assert final is not None
    assert final.text == 'Wir haben bereits einen Anbieter'
    assert final.kind == 'final'
    assert handle.finalize() is None  # nothing in progress anymore


def test_second_utterance_on_same_track_consumes_next_script_line():
    provider = SimulatedASRProvider(script={'inbound': ['erste Aussage', 'zweite Aussage']})
    handle = provider.start_stream(track='inbound')
    handle.feed_audio(b'', is_speaking=True)
    first = handle.finalize()
    handle.feed_audio(b'', is_speaking=True)
    second = handle.finalize()
    assert first.text == 'erste Aussage'
    assert second.text == 'zweite Aussage'


def test_unscripted_track_produces_obviously_fake_placeholder_not_a_plausible_transcript():
    provider = SimulatedASRProvider()  # no script at all
    handle = provider.start_stream(track='inbound')
    handle.feed_audio(b'', is_speaking=True)
    final = handle.finalize()
    assert final.text == PLACEHOLDER_TEXT
    assert 'unavailable' in final.text.lower()


def test_tracks_are_independent_streams():
    provider = SimulatedASRProvider(script={'inbound': ['prospect text'], 'outbound': ['seller text']})
    inbound_handle = provider.start_stream(track='inbound')
    outbound_handle = provider.start_stream(track='outbound')
    inbound_handle.feed_audio(b'', is_speaking=True)
    outbound_handle.feed_audio(b'', is_speaking=True)
    assert inbound_handle.finalize().text == 'prospect text'
    assert outbound_handle.finalize().text == 'seller text'
