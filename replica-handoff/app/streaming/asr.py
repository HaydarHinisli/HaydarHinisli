"""Streaming ASR seam (Sprint 2) — same seam pattern as app/secrets.py's
SecretsProvider: a Protocol plus exactly one implementation today, so a real vendor
(Deepgram, Google STT, Twilio Voice Intelligence, OpenAI Realtime transcription, ...)
can be dropped in later without touching the turn-detection/central-processing code
built on top of it.

`SimulatedASRProvider` is NOT real speech recognition — there is no ASR model here,
and no live ASR vendor is reachable from this environment. It exists so the REST of
the real-time pipeline (VAD-driven speaking/silence, turn detection, the central
turn-processing path, end-to-end latency instrumentation) can be built and proven
today against a faithful protocol-level simulation, while making that limitation
impossible to miss: any utterance the caller didn't pre-register via `script` comes
back as an obviously-fake placeholder string, never something that could pass for a
plausible (but wrong) transcript. See docs/DECISIONS.md ADR-042 for the
interim/final architectural guarantee this seam is built around: an interim event
can never itself reach ConversationState or Suggestion.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Protocol

PLACEHOLDER_TEXT = '[transcription unavailable: no real ASR provider configured — SimulatedASRProvider placeholder]'


@dataclass
class ASREvent:
    kind: str  # 'interim' | 'final'
    track: str
    text: str
    t_monotonic: float


class ASRStreamHandle(Protocol):
    def feed_audio(self, payload: bytes, *, is_speaking: bool) -> ASREvent | None: ...
    def finalize(self) -> ASREvent | None: ...


class ASRProvider(Protocol):
    def start_stream(self, *, track: str) -> ASRStreamHandle: ...


class _SimulatedASRStreamHandle:
    def __init__(self, *, track: str, script: list[str]):
        self.track = track
        self._script = list(script)
        self._script_index = 0
        self._speaking = False
        self._words: list[str] = []
        self._word_cursor = 0

    def feed_audio(self, payload: bytes, *, is_speaking: bool) -> ASREvent | None:
        now = time.monotonic()
        if is_speaking and not self._speaking:
            self._speaking = True
            text = self._script[self._script_index] if self._script_index < len(self._script) else PLACEHOLDER_TEXT
            self._script_index += 1
            self._words = text.split()
            self._word_cursor = 0
        if not is_speaking:
            return None
        # Mimics real streaming ASR's incremental interim growth: one more word of
        # the (simulated) utterance per chunk while speech continues.
        if self._word_cursor < len(self._words):
            self._word_cursor += 1
        partial = ' '.join(self._words[:self._word_cursor])
        return ASREvent(kind='interim', track=self.track, text=partial, t_monotonic=now)

    def finalize(self) -> ASREvent | None:
        if not self._speaking:
            return None
        self._speaking = False
        text = ' '.join(self._words)
        self._words = []
        self._word_cursor = 0
        if not text:
            return None
        return ASREvent(kind='final', track=self.track, text=text, t_monotonic=time.monotonic())


class SimulatedASRProvider:
    """`script` maps track name -> ordered list of utterance texts, standing in for
    what a real ASR would have transcribed from that track's actual audio content
    (this provider has no way to know that — it only ever sees whether the caller's
    VAD says the track is currently speaking). Each track's utterances are consumed
    in order as that track's speech segments finalize."""

    def __init__(self, script: dict[str, list[str]] | None = None):
        self._script = {track: list(lines) for track, lines in (script or {}).items()}

    def start_stream(self, *, track: str) -> _SimulatedASRStreamHandle:
        return _SimulatedASRStreamHandle(track=track, script=self._script.get(track, []))


def get_asr_provider() -> ASRProvider:
    """FastAPI dependency factory (app/main.py's `/ws/twilio-media`) — the one seam
    swap point for a real ASR vendor later. Overridden in tests via
    `app.dependency_overrides[get_asr_provider]` to inject a scripted
    SimulatedASRProvider instead of the default unscripted one."""
    return SimulatedASRProvider()
