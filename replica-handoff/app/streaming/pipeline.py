"""Media stream pipeline glue (Sprint 2/2B): wires MediaStreamSession (track-separated
transport parsing + diagnostics) -> VoiceActivityDetector (per track) -> ASRProvider
(per track) -> TurnDetector -> the central turn-processing path
(app/services/turn_pipeline.process_final_turn()), instrumented end-to-end with
app/services/latency_trace.LatencyTrace.

Architectural guarantee (requirement 5 — interim transcripts must never themselves
advance state): interim ASR events only ever reach `_on_interim` below, which does
nothing but record the latest partial text for observability — it has no access to
`process_final_turn`, `apply_turn`, or any DB session. Only `_handle_silence()`,
triggered by a track's OWN VAD falling silent, can produce a final transcript and
call `_process_turn()`. There is exactly one call site of `process_final_turn()` in
this entire module.

Each finalized turn is processed on its own, short-lived DB session (`SessionLocal()`,
opened and closed around exactly one `process_final_turn()` call) — never one
long-lived session held open for the whole WebSocket connection, matching the
one-Session-per-unit-of-work discipline used everywhere else in this codebase
(app/db.py's `get_db()`).

Async (Sprint 2B, ADR-044): consuming media/stop is now a coroutine, since a real
ASR provider's feed/poll/finalize calls are themselves async I/O against an
independent WebSocket connection — see app/streaming/asr.py's module docstring.
"""
from __future__ import annotations
import logging
import time

from ..db import SessionLocal
from ..models import Call
from ..services.latency_trace import LatencyTrace, build_latency_trace_row
from ..services.turn_pipeline import process_final_turn
from .asr import ASRProvider, ASRStreamHandle
from .media_stream_session import MediaStreamSession, TRACKS
from .speaker_mapping import SpeakerRoleResolver
from .turn_detector import TurnDetector
from .vad import VoiceActivityDetector

logger = logging.getLogger('replica.streaming')


def _describe_provider(asr_provider: ASRProvider) -> tuple[str, bool]:
    """Returns (name, is_synthetic) for TurnLatencyTrace labelling (ADR-045).
    Avoids importing SimulatedASRProvider by class identity check at module import
    time to sidestep any future circular-import risk; a duck-typed class-name check
    is enough for this purely-cosmetic labelling purpose."""
    class_name = type(asr_provider).__name__
    if class_name == 'SimulatedASRProvider':
        return 'simulated', True
    if class_name == 'DeepgramASRProvider':
        return 'deepgram', False
    return class_name.lower(), False


class MediaStreamPipeline:
    def __init__(self, *, call_id: int, company_id: int, speaker_role_resolver: SpeakerRoleResolver | None = None):
        self.call_id = call_id
        self.company_id = company_id
        self.session = MediaStreamSession()
        self.turn_detector = TurnDetector() if speaker_role_resolver is None else TurnDetector(speaker_role_resolver=speaker_role_resolver)
        self.vads = {t: VoiceActivityDetector() for t in TRACKS}
        self.asr_handles: dict[str, ASRStreamHandle] = {}
        self.active_traces: dict[str, LatencyTrace | None] = {t: None for t in TRACKS}
        self.latest_interim: dict[str, str] = {t: '' for t in TRACKS}
        # Sprint 2B (ADR-045): stamped onto every TurnLatencyTrace row this pipeline
        # produces, so a real vs. synthetic measurement can never be confused later.
        self.asr_provider_name = 'simulated'
        self.is_synthetic = True
        # For inspection/tests — not itself part of any compliance/business record.
        self.processed_turns: list[dict] = []

    @classmethod
    async def create(
        cls, *, call_id: int, company_id: int, asr_provider: ASRProvider,
        speaker_role_resolver: SpeakerRoleResolver | None = None,
    ) -> 'MediaStreamPipeline':
        pipeline = cls(call_id=call_id, company_id=company_id, speaker_role_resolver=speaker_role_resolver)
        pipeline.asr_provider_name, pipeline.is_synthetic = _describe_provider(asr_provider)
        for track in TRACKS:
            pipeline.asr_handles[track] = await asr_provider.start_stream(track=track)
        return pipeline

    def consume_start(self, message: dict) -> None:
        self.session.consume_start(message)

    async def consume_stop(self, message: dict) -> None:
        self.session.consume_stop(message)
        now = time.monotonic()
        # A call hanging up mid-utterance must not silently discard whatever was
        # already spoken — finalize any track still mid-speech.
        for track in TRACKS:
            if self.vads[track].is_speaking:
                await self._handle_silence(track, now_monotonic=now)

    async def close(self) -> None:
        for handle in self.asr_handles.values():
            await handle.close()

    async def consume_media(self, message: dict) -> dict:
        now = time.monotonic()
        chunk_info = self.session.consume_media(message, now_monotonic=now)
        track = chunk_info['track']
        if track not in TRACKS:
            # Transport-layer anomaly (unrecognized track name) — never fed into
            # VAD/ASR/turn detection, so it can never be misread as ASR or
            # SalesBrain behavior.
            logger.warning('media stream: unrecognized track', extra={'fields': {'call_id': self.call_id, 'track': track}})
            return chunk_info

        if chunk_info['chunk_status'] not in ('ok', 'unparseable'):
            logger.warning('media stream chunk anomaly', extra={'fields': {
                'call_id': self.call_id, 'track': track, 'status': chunk_info['chunk_status'],
            }})
        if chunk_info['is_gap']:
            logger.warning('media stream audio gap', extra={'fields': {'call_id': self.call_id, 'track': track}})

        trace = self.active_traces[track]
        if trace is None:
            trace = LatencyTrace()
            self.active_traces[track] = trace
        trace.mark('audio_received', at_monotonic=now)  # idempotent: first call per utterance wins

        was_speaking = self.vads[track].is_speaking
        is_speaking, _energy = self.vads[track].process_chunk(chunk_info['payload_bytes'])
        self.turn_detector.on_vad_update(track, is_speaking, now_monotonic=now)

        await self.asr_handles[track].feed_audio(chunk_info['payload_bytes'], is_speaking=is_speaking)
        for event in await self.asr_handles[track].poll_events():
            if event.kind == 'interim':
                trace.mark('asr_interim', at_monotonic=now)
                self._on_interim(track, event.text)
            # A provider-native 'final'/speech_final signal here (e.g. Deepgram's
            # is_final=true / speech_final=true) is NOT our turn-end signal — only
            # our own VAD falling silent triggers finalize() below and drives
            # process_final_turn(). It IS captured, with its own timestamp, purely
            # so the two can be compared after the fact (docs/DECISIONS.md ADR-046,
            # Sprint 2B requirement 4: measure before replacing).
            if event.provider_speech_final:
                trace.mark('provider_endpoint_detected', at_monotonic=event.t_monotonic)

        if was_speaking and not is_speaking:
            await self._handle_silence(track, now_monotonic=now)

        return chunk_info

    def _on_interim(self, track: str, text: str) -> None:
        """Side-effect-free by construction: this is the ENTIRE interim-transcript
        path. It updates an in-memory preview value only — no DB session exists in
        this call stack, so it is structurally impossible for an interim transcript
        to reach ConversationState, ConversationStateEvent, or Suggestion. A real
        product would push `text` to the seller's live UI as an early preview
        (docs/ARCHITECTURE.md's "Early Event Classifier" box) — out of scope for
        proving Sprint 2's pipeline shape."""
        self.latest_interim[track] = text

    async def _handle_silence(self, track: str, *, now_monotonic: float) -> None:
        final_event = await self.asr_handles[track].finalize()
        trace = self.active_traces[track]
        self.active_traces[track] = None
        if final_event is None:
            return
        if trace is None:
            trace = LatencyTrace()  # defensive: should not happen if audio_received was ever marked
        trace.mark('asr_final', at_monotonic=now_monotonic)
        turn_event = self.turn_detector.on_turn_ended(track, final_event.text, now_monotonic=now_monotonic)
        trace.mark('turn_end_detected', at_monotonic=now_monotonic)
        if turn_event is None:
            return
        self._process_turn(turn_event, trace)

    def _process_turn(self, turn_event, trace: LatencyTrace) -> None:
        """The ONLY call site of process_final_turn() in this module — the single
        central path for a genuinely final turn (requirement 6)."""
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if call is None:
                logger.error('media stream: call disappeared mid-stream', extra={'fields': {'call_id': self.call_id}})
                return
            result = process_final_turn(
                db, call, turn_event.speaker, turn_event.text, company_id=self.company_id, latency_trace=trace,
            )
            self.processed_turns.append({
                'speaker': turn_event.speaker, 'text': turn_event.text, 'had_overlap': turn_event.had_overlap, **result,
            })
            if result.get('denied') or result.get('duplicate'):
                return
            # Sprint 2 ends at "Suggestion persisted" (see docs/DECISIONS.md
            # ADR-041 / final report) — there is no real UI push mechanism yet for
            # this pipeline, so `suggestion_pushed`/`ui_rendered`/`real_rsl_ms`
            # stay unmarked/NULL rather than being approximated. Marking them here
            # would silently manufacture a fake RSL number, exactly what the
            # explicit "never call internal latency real RSL" requirement forbids.
            row = build_latency_trace_row(
                trace, company_id=self.company_id, call_id=self.call_id,
                turn_id=result.get('turn_id', ''), trace_id=None, speaker=turn_event.speaker,
                asr_provider=self.asr_provider_name, is_synthetic=self.is_synthetic,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()

    def diagnostics_summary(self) -> dict:
        return self.session.diagnostics_summary()
