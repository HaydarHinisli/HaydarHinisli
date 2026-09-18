"""Turn detection (Sprint 2): combines per-track speaking state into speaker-level
domain events — prospect speaking / seller speaking / overlap / speaker change / turn
end — and resolves each track's own finalized utterance into exactly one `TurnEvent`.
This is the component the requirements call out explicitly: REPLICA must be able to
tell "prospect speaks" from "seller speaks" from "overlap" from "speaker change" from
"turn end" as distinct, separately observable facts, not one blended signal.

Deliberate scope limit (see docs/DECISIONS.md ADR-039): who "held the floor" during
genuine overlap (talking over each other) is not algorithmically adjudicated here —
each track's utterance still finalizes independently once THAT track's own VAD
detects silence; overlap is only flagged (`had_overlap=True` on both resulting
TurnEvents), not resolved into a single winner. A more sophisticated barge-in model
is future work, not required to prove Sprint 2's target pipeline shape.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .media_stream_session import INBOUND, OUTBOUND

TRACK_TO_SPEAKER = {INBOUND: 'prospect', OUTBOUND: 'seller'}


@dataclass
class TurnEvent:
    speaker: str  # 'prospect' | 'seller'
    text: str
    had_overlap: bool
    t_speech_started_monotonic: float
    t_turn_end_detected_monotonic: float


@dataclass
class VadUpdateResult:
    speaker_changed: bool
    overlap_started: bool
    overlap_active: bool


@dataclass
class TurnDetector:
    speaking: dict[str, bool] = field(default_factory=lambda: {INBOUND: False, OUTBOUND: False})
    last_active_speaker: str | None = None
    _overlap_flag: dict[str, bool] = field(default_factory=lambda: {INBOUND: False, OUTBOUND: False})
    _speech_started_monotonic: dict[str, float | None] = field(default_factory=lambda: {INBOUND: None, OUTBOUND: None})

    def on_vad_update(self, track: str, is_speaking: bool, *, now_monotonic: float) -> VadUpdateResult:
        """Call on every chunk's VAD result for `track`."""
        was_speaking = self.speaking.get(track, False)
        overlap_started = False
        if is_speaking and not was_speaking:
            self._speech_started_monotonic[track] = now_monotonic
            other = OUTBOUND if track == INBOUND else INBOUND
            if self.speaking.get(other, False):
                overlap_started = True
                self._overlap_flag[track] = True
                self._overlap_flag[other] = True
        self.speaking[track] = is_speaking

        speaker_changed = False
        if is_speaking:
            speaker = TRACK_TO_SPEAKER.get(track, track)
            if self.last_active_speaker is not None and self.last_active_speaker != speaker:
                speaker_changed = True
            self.last_active_speaker = speaker

        overlap_active = self.speaking.get(INBOUND, False) and self.speaking.get(OUTBOUND, False)
        return VadUpdateResult(speaker_changed=speaker_changed, overlap_started=overlap_started, overlap_active=overlap_active)

    def on_turn_ended(self, track: str, text: str, *, now_monotonic: float) -> TurnEvent | None:
        """Call when the ASR handle's finalize() produced a transcript for `track`
        (that track's VAD hangover elapsed — it fell silent). Returns the resolved
        TurnEvent, or None if there is nothing to report (empty finalize)."""
        if not text:
            return None
        started = self._speech_started_monotonic.get(track)
        if started is None:
            started = now_monotonic
        had_overlap = self._overlap_flag.get(track, False)
        self._overlap_flag[track] = False
        self._speech_started_monotonic[track] = None
        return TurnEvent(
            speaker=TRACK_TO_SPEAKER.get(track, track), text=text, had_overlap=had_overlap,
            t_speech_started_monotonic=started, t_turn_end_detected_monotonic=now_monotonic,
        )
