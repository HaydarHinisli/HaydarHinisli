"""Deepgram streaming ASR adapter (Sprint 2B, docs/DECISIONS.md ADR-045).

**Honesty notice, read before touching this file**: this adapter is implemented per
Deepgram's publicly documented streaming API (Nova-3, the `/v1/listen` WebSocket
endpoint, its `Results`/`Metadata`/`UtteranceEnd` message shapes, and its
`Finalize`/`CloseStream` control messages) as understood at the time this was
written. **It has never been connected to a real Deepgram account** — this
environment has no `DEEPGRAM_API_KEY` and no network path to verify wire behavior
against the live service. `tests/test_streaming_deepgram_provider.py` verifies this
adapter's OWN logic (message parsing, reconnect/backoff, the Finalize flow, event
mapping into `ASREvent`) against a local fake server that speaks the same documented
protocol shape — that proves the adapter's plumbing is internally correct, it does
NOT prove the real Deepgram service behaves exactly as assumed here. **This MUST be
verified against a live Deepgram account before it is used for anything beyond
further development** — see the Sprint 2B report for exactly what remains open.

Kept entirely behind the `ASRProvider`/`ASRStreamHandle` protocol (app/streaming/
asr.py) — no Deepgram-specific type or field ever needs to leak into
`app/streaming/turn_detector.py`, `app/streaming/pipeline.py`, or any SalesBrain/
ConversationState code. The `provider_speech_final`/`words` fields on `ASREvent` are
provider-agnostic parts of that same shared protocol, not Deepgram-specific either.

Turn-end authority (Sprint 2B requirement 4): our own VAD (`app/streaming/vad.py`)
remains the sole trigger for `finalize()` — this adapter's role is only to answer
"what did Deepgram transcribe" at that point, using its `Finalize` control message to
prompt Deepgram to flush its buffer promptly. Deepgram's own `speech_final`/
`is_final` signals are surfaced via `ASREvent.provider_speech_final` purely for later
comparison (docs/DECISIONS.md ADR-046) — never used to decide when an utterance ends.
"""
from __future__ import annotations
import asyncio
import json
import logging

import websockets
from websockets.asyncio.client import ClientConnection

from .asr import ASREvent

logger = logging.getLogger('replica.streaming.deepgram')

_CONNECT_TIMEOUT_S = 5.0
_RECONNECT_BACKOFFS_S = (0.5, 1.5, 3.0)  # a handful of quick retries, not indefinite
_FINALIZE_WAIT_TIMEOUT_S = 1.5  # bounded: never block the pipeline indefinitely on the network


def _build_url(*, region: str, model: str, language: str, keyterms: list[str] | None) -> str:
    host = 'api.eu.deepgram.com' if region.strip().lower() == 'eu' else 'api.deepgram.com'
    params = {
        'model': model,
        'language': language,
        'interim_results': 'true',
        'mip_opt_out': 'true',
        # Twilio Media Streams' documented default audio format (docs/PROVIDER_REFERENCES.md).
        'encoding': 'mulaw',
        'sample_rate': '8000',
        'channels': '1',
    }
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    for term in keyterms or []:
        query += f'&keyterm={term}'
    return f'wss://{host}/v1/listen?{query}'


class DeepgramStreamHandle:
    def __init__(
        self, *, track: str, api_key: str, region: str, model: str, language: str,
        keyterms: list[str] | None = None, _url_override: str | None = None,
    ):
        self.track = track
        # _url_override exists solely so tests can point this handle at a local
        # fake server speaking Deepgram's documented protocol shape (see
        # tests/test_streaming_deepgram_provider.py) instead of the real service —
        # never set in production code paths.
        self._url = _url_override or _build_url(region=region, model=model, language=language, keyterms=keyterms)
        self._api_key = api_key
        self._connection: ClientConnection | None = None
        self._receiver_task: asyncio.Task | None = None
        self._event_queue: asyncio.Queue[ASREvent] = asyncio.Queue()
        self._final_pieces: list[str] = []
        self._final_words: list[dict] = []
        self._closed = False
        self._connect_lock = asyncio.Lock()

    async def _ensure_connected(self) -> bool:
        """Returns True if a connection is available (existing or freshly
        (re)established), False if it could not be established after retrying —
        callers must degrade gracefully (see feed_audio/finalize below), never crash
        the pipeline over a single track's ASR connection failing."""
        if self._connection is not None or self._closed:
            return self._connection is not None
        async with self._connect_lock:
            if self._connection is not None:
                return True
            for attempt, backoff in enumerate((0.0, *_RECONNECT_BACKOFFS_S)):
                if backoff:
                    await asyncio.sleep(backoff)
                try:
                    self._connection = await asyncio.wait_for(
                        websockets.connect(self._url, additional_headers={'Authorization': f'Token {self._api_key}'}),
                        timeout=_CONNECT_TIMEOUT_S,
                    )
                    self._receiver_task = asyncio.ensure_future(self._receive_loop())
                    logger.info('deepgram connected', extra={'fields': {'track': self.track, 'attempt': attempt}})
                    return True
                except Exception as exc:  # noqa: BLE001 — any connect failure is a reconnect-and-retry case, not a crash
                    logger.warning('deepgram connect failed', extra={'fields': {'track': self.track, 'attempt': attempt, 'error': str(exc)}})
            logger.error('deepgram connection could not be established after retries', extra={'fields': {'track': self.track}})
            return False

    async def _receive_loop(self) -> None:
        assert self._connection is not None
        try:
            async for raw in self._connection:
                self._handle_message(raw)
        except websockets.ConnectionClosed:
            logger.warning('deepgram connection closed', extra={'fields': {'track': self.track}})
        except Exception as exc:  # noqa: BLE001 — a receiver crash must not take down the pipeline
            logger.error('deepgram receive loop error', extra={'fields': {'track': self.track, 'error': str(exc)}})
        finally:
            self._connection = None

    def _handle_message(self, raw) -> None:
        if isinstance(raw, (bytes, bytearray)):
            return  # Deepgram's control/result channel is text/JSON; binary is unexpected here
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning('deepgram sent non-JSON message', extra={'fields': {'track': self.track}})
            return

        msg_type = payload.get('type')
        if msg_type == 'Results':
            alternatives = payload.get('channel', {}).get('alternatives', [])
            transcript = alternatives[0].get('transcript', '') if alternatives else ''
            is_final = bool(payload.get('is_final'))
            speech_final = bool(payload.get('speech_final'))
            words = alternatives[0].get('words') if alternatives else None
            if is_final and transcript:
                self._final_pieces.append(transcript)
                if words:
                    self._final_words.extend(words)
            kind = 'final' if is_final else 'interim'
            display_text = ' '.join([*self._final_pieces, transcript]) if not is_final else ' '.join(self._final_pieces)
            self._event_queue.put_nowait(ASREvent(
                kind=kind, track=self.track, text=display_text.strip(), t_monotonic=_now(),
                provider_speech_final=speech_final, words=words,
            ))
        elif msg_type == 'UtteranceEnd':
            # Deepgram's own utterance-boundary signal when `utterance_end_ms` is
            # configured — captured the same way as speech_final for comparison,
            # not requested to be enabled by name here since it requires an extra
            # config param; left for a later benchmarking pass once real traffic
            # exists (see Sprint 2B report).
            self._event_queue.put_nowait(ASREvent(
                kind='final', track=self.track, text=' '.join(self._final_pieces).strip(),
                t_monotonic=_now(), provider_speech_final=True, words=self._final_words or None,
            ))
        elif msg_type in ('Metadata', 'Warning'):
            logger.info('deepgram %s message', msg_type, extra={'fields': {'track': self.track, 'payload': payload}})
        elif msg_type == 'Error':
            logger.error('deepgram error message', extra={'fields': {'track': self.track, 'payload': payload}})

    async def feed_audio(self, payload: bytes, *, is_speaking: bool) -> None:
        """Deepgram does its own voice-activity handling; audio is always forwarded
        (silence included — this is normal for streaming ASR), `is_speaking` is
        accepted only for protocol-compatibility with SimulatedASRProvider and
        otherwise ignored here."""
        if self._closed or not payload:
            return
        if not await self._ensure_connected():
            return  # degrade gracefully — this track's ASR is temporarily unavailable
        try:
            await self._connection.send(payload)
        except websockets.ConnectionClosed:
            self._connection = None  # will reconnect on next call

    async def poll_events(self) -> list[ASREvent]:
        events = []
        while not self._event_queue.empty():
            events.append(self._event_queue.get_nowait())
        return events

    async def finalize(self) -> ASREvent | None:
        """Prompts Deepgram to flush its buffer via the documented `Finalize`
        control message, waits briefly for the resulting final transcript(s), then
        returns the accumulated final text for this utterance and resets state for
        the next one. Bounded wait (`_FINALIZE_WAIT_TIMEOUT_S`) — a slow or
        unresponsive provider must never block the pipeline indefinitely; whatever
        has accumulated so far is returned instead."""
        if self._connection is not None:
            try:
                await self._connection.send(json.dumps({'type': 'Finalize'}))
                await asyncio.sleep(_FINALIZE_WAIT_TIMEOUT_S)
                await self.poll_events()  # drain; _handle_message() already updated self._final_pieces
            except websockets.ConnectionClosed:
                self._connection = None
        text = ' '.join(self._final_pieces).strip()
        words = self._final_words or None
        self._final_pieces = []
        self._final_words = []
        if not text:
            return None
        return ASREvent(kind='final', track=self.track, text=text, t_monotonic=_now(), provider_speech_final=True, words=words)

    async def close(self) -> None:
        self._closed = True
        if self._connection is not None:
            try:
                await self._connection.send(json.dumps({'type': 'CloseStream'}))
            except websockets.ConnectionClosed:
                pass
            await self._connection.close()
            self._connection = None
        if self._receiver_task is not None:
            self._receiver_task.cancel()


def _now() -> float:
    import time
    return time.monotonic()


class DeepgramASRProvider:
    def __init__(
        self, *, api_key: str, region: str = 'eu', model: str = 'nova-3', language: str = 'de',
        keyterms: list[str] | None = None, _url_override: str | None = None,
    ):
        self._api_key = api_key
        self._region = region
        self._model = model
        self._language = language
        self._keyterms = keyterms
        self._url_override = _url_override

    async def start_stream(self, *, track: str) -> DeepgramStreamHandle:
        return DeepgramStreamHandle(
            track=track, api_key=self._api_key, region=self._region, model=self._model,
            language=self._language, keyterms=self._keyterms, _url_override=self._url_override,
        )
