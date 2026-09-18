"""Streaming ASR seam (Sprint 2/2B) — same seam pattern as app/secrets.py's
SecretsProvider: a Protocol plus swappable implementations, so a real vendor drops
in without touching turn-detection/central-processing code built on top of it.

Async protocol (Sprint 2B, docs/DECISIONS.md ADR-044): a real streaming ASR vendor
(app/streaming/deepgram_provider.py) sends audio and receives transcript messages
over an independent, asynchronous WebSocket connection — results do not arrive in
lockstep with each audio chunk sent, the way `SimulatedASRProvider`'s original
synchronous design assumed. The protocol is therefore:
- `feed_audio()`: push one chunk of audio to the provider; never blocks waiting for
  a result.
- `poll_events()`: non-blocking drain of whatever transcript events have arrived
  since the last call (may be empty).
- `finalize()`: called when OUR OWN voice-activity detection (not the provider's)
  decides a track has fallen silent; returns the accumulated final transcript for
  that utterance, waiting briefly for a real provider to flush its buffer if needed.
- `close()`: releases the underlying connection when the media stream ends.

`SimulatedASRProvider` is NOT real speech recognition — there is no ASR model here.
It exists so the rest of the real-time pipeline can be built and proven against a
faithful protocol-level simulation. Any utterance the caller didn't pre-register via
`script` comes back as an obviously-fake placeholder string, never something that
could pass for a plausible (but wrong) transcript. See docs/DECISIONS.md ADR-042 for
the interim/final architectural guarantee this seam is built around: an interim
event can never itself reach ConversationState or Suggestion.
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
    # Sprint 2B: the provider's OWN endpointing signal (e.g. Deepgram's
    # speech_final), captured for later comparison against our VAD-driven turn-end
    # (docs/DECISIONS.md ADR-046) — never authoritative for turn-end decisions.
    provider_speech_final: bool = False
    # Word-level timestamps when the provider supplies them: list of
    # {'word': str, 'start': float, 'end': float} (seconds from utterance start).
    words: list[dict] | None = None


class ASRStreamHandle(Protocol):
    async def feed_audio(self, payload: bytes, *, is_speaking: bool) -> None: ...
    async def poll_events(self) -> list[ASREvent]: ...
    async def finalize(self) -> ASREvent | None: ...
    async def close(self) -> None: ...


class ASRProvider(Protocol):
    async def start_stream(self, *, track: str) -> ASRStreamHandle: ...


class _SimulatedASRStreamHandle:
    def __init__(self, *, track: str, script: list[str]):
        self.track = track
        self._script = list(script)
        self._script_index = 0
        self._speaking = False
        self._words: list[str] = []
        self._word_cursor = 0
        self._pending: list[ASREvent] = []

    async def feed_audio(self, payload: bytes, *, is_speaking: bool) -> None:
        now = time.monotonic()
        if is_speaking and not self._speaking:
            self._speaking = True
            text = self._script[self._script_index] if self._script_index < len(self._script) else PLACEHOLDER_TEXT
            self._script_index += 1
            self._words = text.split()
            self._word_cursor = 0
        if not is_speaking:
            return
        # Mimics real streaming ASR's incremental interim growth: one more word of
        # the (simulated) utterance per chunk while speech continues.
        if self._word_cursor < len(self._words):
            self._word_cursor += 1
        partial = ' '.join(self._words[:self._word_cursor])
        self._pending.append(ASREvent(kind='interim', track=self.track, text=partial, t_monotonic=now))

    async def poll_events(self) -> list[ASREvent]:
        pending, self._pending = self._pending, []
        return pending

    async def finalize(self) -> ASREvent | None:
        if not self._speaking:
            return None
        self._speaking = False
        text = ' '.join(self._words)
        self._words = []
        self._word_cursor = 0
        if not text:
            return None
        return ASREvent(kind='final', track=self.track, text=text, t_monotonic=time.monotonic())

    async def close(self) -> None:
        pass


class SimulatedASRProvider:
    """`script` maps track name -> ordered list of utterance texts, standing in for
    what a real ASR would have transcribed from that track's actual audio content
    (this provider has no way to know that — it only ever sees whether the caller's
    VAD says the track is currently speaking). Each track's utterances are consumed
    in order as that track's speech segments finalize."""

    def __init__(self, script: dict[str, list[str]] | None = None):
        self._script = {track: list(lines) for track, lines in (script or {}).items()}

    async def start_stream(self, *, track: str) -> _SimulatedASRStreamHandle:
        return _SimulatedASRStreamHandle(track=track, script=self._script.get(track, []))


def get_asr_provider() -> ASRProvider:
    """FastAPI dependency factory (app/main.py's `/ws/twilio-media`) — the one seam
    swap point for a real ASR vendor. Reads `REPLICA_ASR_PROVIDER` (default
    `'simulated'`); `'deepgram'` requires `DEEPGRAM_API_KEY` to be configured and
    falls back to the simulated provider with a loud warning if it is not (fail-safe,
    never silently attempts an unauthenticated connection) — see
    docs/DECISIONS.md ADR-045. Overridden in tests via
    `app.dependency_overrides[get_asr_provider]` to inject a scripted
    SimulatedASRProvider regardless of configuration.
    """
    import logging
    from ..config import get_settings

    settings = get_settings()
    provider_name = (settings.replica_asr_provider or 'simulated').strip().lower()
    if provider_name == 'simulated':
        return SimulatedASRProvider()
    if provider_name == 'deepgram':
        if not settings.deepgram_api_key:
            logging.getLogger('replica.streaming').error(
                'REPLICA_ASR_PROVIDER=deepgram but DEEPGRAM_API_KEY is not set — '
                'falling back to SimulatedASRProvider (no real transcription).'
            )
            return SimulatedASRProvider()
        from .deepgram_provider import DeepgramASRProvider
        return DeepgramASRProvider(
            api_key=settings.deepgram_api_key, region=settings.deepgram_region,
            model=settings.deepgram_model, language=settings.deepgram_language,
        )
    logging.getLogger('replica.streaming').error(
        'Unknown REPLICA_ASR_PROVIDER=%r — falling back to SimulatedASRProvider.', provider_name,
    )
    return SimulatedASRProvider()
