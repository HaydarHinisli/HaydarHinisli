"""Sprint 2 requirement 2: prospect speaks / seller speaks / overlap / speaker
change / turn end as distinct, separately observable signals."""
from app.streaming.media_stream_session import INBOUND, OUTBOUND
from app.streaming.turn_detector import TurnDetector


def test_prospect_speaking_is_reported_distinctly():
    td = TurnDetector()
    result = td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    assert td.speaking[INBOUND] is True
    assert td.speaking[OUTBOUND] is False
    assert result.overlap_active is False


def test_seller_speaking_is_reported_distinctly():
    td = TurnDetector()
    td.on_vad_update(OUTBOUND, True, now_monotonic=0.0)
    assert td.speaking[OUTBOUND] is True
    assert td.speaking[INBOUND] is False


def test_overlap_detected_when_both_tracks_speak_simultaneously():
    td = TurnDetector()
    td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    result = td.on_vad_update(OUTBOUND, True, now_monotonic=0.1)
    assert result.overlap_started is True
    assert result.overlap_active is True


def test_speaker_change_detected_between_alternating_tracks():
    td = TurnDetector()
    td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    td.on_vad_update(INBOUND, False, now_monotonic=1.0)
    result = td.on_vad_update(OUTBOUND, True, now_monotonic=1.5)
    assert result.speaker_changed is True
    assert td.last_active_speaker == 'seller'


def test_no_speaker_change_when_same_track_keeps_talking():
    td = TurnDetector()
    td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    result = td.on_vad_update(INBOUND, True, now_monotonic=0.02)
    assert result.speaker_changed is False


def test_turn_end_resolves_to_exactly_one_turn_event_with_correct_speaker():
    td = TurnDetector()
    td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    td.on_vad_update(INBOUND, False, now_monotonic=1.0)
    turn = td.on_turn_ended(INBOUND, 'Wir haben bereits einen Anbieter.', now_monotonic=1.0)
    assert turn is not None
    assert turn.speaker == 'prospect'
    assert turn.text == 'Wir haben bereits einen Anbieter.'
    assert turn.had_overlap is False
    assert turn.t_turn_end_detected_monotonic == 1.0
    assert turn.t_speech_started_monotonic == 0.0


def test_turn_end_flags_had_overlap_when_overlap_occurred_during_the_utterance():
    td = TurnDetector()
    td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    td.on_vad_update(OUTBOUND, True, now_monotonic=0.5)  # overlap starts
    td.on_vad_update(OUTBOUND, False, now_monotonic=0.8)
    turn_seller = td.on_turn_ended(OUTBOUND, 'kurzer Einwurf', now_monotonic=0.8)
    assert turn_seller.had_overlap is True

    td.on_vad_update(INBOUND, False, now_monotonic=1.2)
    turn_prospect = td.on_turn_ended(INBOUND, 'langer Satz', now_monotonic=1.2)
    assert turn_prospect.had_overlap is True  # both sides flagged, neither adjudicated as "winner"


def test_turn_end_with_empty_text_returns_none():
    td = TurnDetector()
    assert td.on_turn_ended(INBOUND, '', now_monotonic=1.0) is None


def test_each_track_finalizes_independently_even_when_overlapping():
    """Deliberate scope limit (ADR-039): overlap is flagged, not adjudicated — each
    track still produces its own TurnEvent once IT falls silent."""
    td = TurnDetector()
    td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    td.on_vad_update(OUTBOUND, True, now_monotonic=0.3)
    td.on_vad_update(OUTBOUND, False, now_monotonic=0.6)
    seller_turn = td.on_turn_ended(OUTBOUND, 'seller text', now_monotonic=0.6)
    td.on_vad_update(INBOUND, False, now_monotonic=1.0)
    prospect_turn = td.on_turn_ended(INBOUND, 'prospect text', now_monotonic=1.0)
    assert seller_turn.speaker == 'seller'
    assert prospect_turn.speaker == 'prospect'
