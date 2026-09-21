"""Media stream pipeline glue (Sprint 2/2B/3A): wires MediaStreamSession
(track-separated transport parsing + diagnostics) -> VoiceActivityDetector (per
track) -> ASRProvider (per track) -> TurnDetector -> the central turn-processing
path (app/services/turn_pipeline.process_final_turn()) -> Live Suggestion Push
(app/services/live_push.LiveSuggestionHub, Sprint 3A ADR-048), instrumented
end-to-end with app/services/latency_trace.LatencyTrace.

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
import uuid

from ..db import SessionLocal
from ..models import Call
from ..services.latency_trace import LatencyTrace, build_latency_trace_row
from ..services.live_push import get_live_suggestion_hub, guidance_hint
from ..services.turn_pipeline import process_final_turn
from .asr import ASRProvider, ASRStreamHandle
from .media_stream_session import MediaStreamSession, TRACKS
from .speaker_mapping import SpeakerRoleResolver
from .turn_detector import TurnDetector
from .vad import VoiceActivityDetector

logger = logging.getLogger('replica.streaming')


class PipelineStatus:
    """Red-team hardening (docs/DECISIONS.md ADR-063, item 3): the analysis/
    pipeline state pushed to `/ws/live/{call_id}` as `{'type': 'pipeline_status',
    'status': ..., 'detail': ...}` (app/services/live_push.LiveSuggestionHub.
    push_status()) — deliberately independent of the Twilio call's own connection
    state (a phone call connecting proves nothing about REPLICA's own pipeline
    actually working). Raw string values only; German display labels live
    entirely in app/static/live.html, matching this codebase's existing
    convention for translating raw enum-ish values at the UI edge (see
    live.html's PHASE_LABELS)."""
    MEDIA_STREAM_CONNECTED = 'media_stream_connected'
    DEEPGRAM_CONNECTING = 'deepgram_connecting'
    DEEPGRAM_READY = 'deepgram_ready'
    AUDIO_RECEIVED = 'audio_received'
    TRANSCRIPT_ACTIVE = 'transcript_active'
    SUGGESTION_PIPELINE_READY = 'suggestion_pipeline_ready'
    DISRUPTED = 'disrupted'
    # `disrupted` detail values (frontend maps a subset to a specific label,
    # e.g. "Deepgram nicht verfügbar" — see live.html's ANALYSIS_DETAIL_LABELS):
    DETAIL_DEEPGRAM_UNAVAILABLE = 'deepgram_unavailable'
    DETAIL_MEDIA_STREAM_DISCONNECTED = 'media_stream_disconnected'
    DETAIL_UNTRUSTED_SPEAKER_MAPPING = 'untrusted_speaker_mapping'
    DETAIL_PIPELINE_ERROR = 'pipeline_error'


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
        # Red-team hardening (docs/DECISIONS.md ADR-063, item 3): one-shot flags so
        # each pipeline_status milestone below is pushed exactly once per call,
        # never spammed once-per-chunk/once-per-turn.
        self._audio_received_pushed = False
        self._transcript_active_pushed = False
        self._suggestion_ready_pushed = False
        self._deepgram_ready_pushed = False
        # Tracks each track's ASR connection health across calls to consume_media()
        # so a connect/disconnect TRANSITION can be detected (see ASRStreamHandle.
        # is_connected()'s docstring for why this can never be exception-driven).
        # Assumed connected initially — the first real check happens on that
        # track's first consume_media() call, before which nothing has failed yet.
        self._asr_connected: dict[str, bool] = {t: True for t in TRACKS}
        # item 9: a per-track correlation id for the ASR stream this pipeline
        # opened for it — logged once (never any transcript content) so the real
        # call's speaker mapping can be technically reconstructed afterward: which
        # Twilio track -> which SpeakerRole -> which ASR session -> which Turns.
        self.asr_session_ids: dict[str, str] = {t: uuid.uuid4().hex for t in TRACKS}

    @classmethod
    async def create(
        cls, *, call_id: int, company_id: int, asr_provider: ASRProvider,
        speaker_role_resolver: SpeakerRoleResolver | None = None,
    ) -> 'MediaStreamPipeline':
        pipeline = cls(call_id=call_id, company_id=company_id, speaker_role_resolver=speaker_role_resolver)
        pipeline.asr_provider_name, pipeline.is_synthetic = _describe_provider(asr_provider)
        for track in TRACKS:
            pipeline.asr_handles[track] = await asr_provider.start_stream(track=track)
        # item 9 instrumentation: which Twilio track maps to which SpeakerRole for
        # THIS call, and which ASR session id correlates to each — logged exactly
        # once per call, structured, content-free. Answers "inbound_track ->
        # seller?" / "outbound_track -> prospect?" afterward without needing to
        # infer it from anything else. The resolver lives in exactly one place
        # (app/streaming/speaker_mapping.py) — if the real call shows this mapping
        # is wrong, the correction belongs there, never as a second hardcoded
        # mapping introduced here or anywhere else.
        resolver = pipeline.turn_detector.speaker_role_resolver
        logger.info('speaker mapping instrumented for this call', extra={'fields': {
            'call_id': call_id,
            'topology': getattr(resolver, 'TOPOLOGY_NAME', type(resolver).__name__),
            'track_to_speaker_role': {track: resolver.resolve(track) for track in TRACKS},
            'asr_session_ids': pipeline.asr_session_ids,
            'asr_provider': pipeline.asr_provider_name,
        }})
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

        if not self._audio_received_pushed:
            self._audio_received_pushed = True
            await get_live_suggestion_hub().push_status(
                call_id=self.call_id, company_id=self.company_id, status=PipelineStatus.AUDIO_RECEIVED,
            )

        was_speaking = self.vads[track].is_speaking
        is_speaking, _energy = self.vads[track].process_chunk(chunk_info['payload_bytes'])
        self.turn_detector.on_vad_update(track, is_speaking, now_monotonic=now)

        await self.asr_handles[track].feed_audio(chunk_info['payload_bytes'], is_speaking=is_speaking)

        # Red-team hardening (docs/DECISIONS.md ADR-063, item 3/4): a real ASR
        # provider's connection can drop (or recover) mid-call without ever
        # raising an exception anywhere in this stack — is_connected() is the
        # only way to see that transition. Checked once per chunk here, but only
        # ACTED on when it actually changes, so a healthy connection never spams
        # a status push, and an unhealthy one is not reported over and over.
        was_connected = self._asr_connected.get(track, True)
        is_connected = self.asr_handles[track].is_connected()
        self._asr_connected[track] = is_connected
        if self.asr_provider_name == 'deepgram':
            if is_connected and (not was_connected or not self._deepgram_ready_pushed):
                self._deepgram_ready_pushed = True
                await get_live_suggestion_hub().push_status(
                    call_id=self.call_id, company_id=self.company_id, status=PipelineStatus.DEEPGRAM_READY,
                )
            elif was_connected and not is_connected:
                hub = get_live_suggestion_hub()
                await hub.push_status(
                    call_id=self.call_id, company_id=self.company_id, status=PipelineStatus.DISRUPTED,
                    detail=PipelineStatus.DETAIL_DEEPGRAM_UNAVAILABLE,
                )
                await hub.push_suggestion_stale(
                    call_id=self.call_id, company_id=self.company_id, reason=PipelineStatus.DETAIL_DEEPGRAM_UNAVAILABLE,
                )

        for event in await self.asr_handles[track].poll_events():
            if not self._transcript_active_pushed:
                self._transcript_active_pushed = True
                await get_live_suggestion_hub().push_status(
                    call_id=self.call_id, company_id=self.company_id, status=PipelineStatus.TRANSCRIPT_ACTIVE,
                )
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
        await self._process_turn(turn_event, trace)

    async def _process_turn(self, turn_event, trace: LatencyTrace) -> None:
        """The ONLY call site of process_final_turn() in this module — the single
        central path for a genuinely final turn (requirement 6)."""
        # Sprint 3A (ADR-048): one id per finalized turn, correlating the Suggestion
        # row, the live-push envelope, the TurnLatencyTrace row, and (later,
        # out-of-band) the browser's own Render-ACK — generated here rather than
        # left None, since a real end-to-end RSL measurement needs a single id that
        # survives across the DB commit and the async WS push both.
        trace_id = str(uuid.uuid4())
        # Red-team hardening (docs/DECISIONS.md ADR-063, item 4/9): the resolver
        # (app/streaming/speaker_mapping.py) only ever returns 'seller'/'prospect'
        # for the two tracks that actually exist on a Twilio Media Stream today —
        # this branch is currently unreachable in production, kept as fail-closed
        # defense-in-depth rather than trusting that invariant silently forever.
        # Data is still persisted below (never silently dropped), but the seller's
        # live UI is told not to trust whatever suggestion results from it.
        if turn_event.speaker not in ('seller', 'prospect'):
            hub = get_live_suggestion_hub()
            await hub.push_status(
                call_id=self.call_id, company_id=self.company_id, status=PipelineStatus.DISRUPTED,
                detail=PipelineStatus.DETAIL_UNTRUSTED_SPEAKER_MAPPING,
            )
            await hub.push_suggestion_stale(
                call_id=self.call_id, company_id=self.company_id, reason=PipelineStatus.DETAIL_UNTRUSTED_SPEAKER_MAPPING,
            )
            logger.error('media stream: untrusted speaker mapping — unrecognized role', extra={'fields': {
                'call_id': self.call_id, 'track_role': turn_event.speaker,
            }})
        db = SessionLocal()
        try:
            call = db.get(Call, self.call_id)
            if call is None:
                logger.error('media stream: call disappeared mid-stream', extra={'fields': {'call_id': self.call_id}})
                return
            result = process_final_turn(
                db, call, turn_event.speaker, turn_event.text, company_id=self.company_id,
                latency_trace=trace, trace_id=trace_id,
            )
            if not self._suggestion_ready_pushed:
                self._suggestion_ready_pushed = True
                await get_live_suggestion_hub().push_status(
                    call_id=self.call_id, company_id=self.company_id, status=PipelineStatus.SUGGESTION_PIPELINE_READY,
                )
            self.processed_turns.append({
                'speaker': turn_event.speaker, 'text': turn_event.text, 'had_overlap': turn_event.had_overlap, **result,
            })
            if result.get('denied') or result.get('duplicate'):
                return
            suggestion_payload = result.get('suggestion_payload')
            if suggestion_payload is not None:
                # ADR-051: `push_enqueued` marks handing the persisted Suggestion to
                # the live-delivery layer (renamed from `suggestion_pushed`) — not
                # confirmed delivery to a browser (there may be zero connected
                # subscribers right now, a valid outcome, not a failure). Separately,
                # `ws_send_completed` marks once the actual WebSocket send(s) for
                # any currently-connected subscribers have finished, isolating
                # hub-handoff latency from network/event-loop latency.
                trace.mark('push_enqueued')
                hub = get_live_suggestion_hub()
                push_payload = {
                    'call_id': self.call_id, 'turn_id': result.get('turn_id'), **suggestion_payload,
                    'guidance_hint': guidance_hint(suggestion_payload.get('strategy')),
                    # Debug-only diagnostics (app/static/live.html's separate debug
                    # panel — Sprint 3A requirement 2): internal engine timings, NEVER
                    # to be shown as or confused with any RSL figure (ADR-021/022/048/051).
                    'debug': {
                        'asr_provider': self.asr_provider_name,
                        'is_synthetic': self.is_synthetic,
                        'latencies_ms': {
                            'audio_to_final': trace.delta_ms('audio_received', 'asr_final'),
                            'turn_detection': trace.delta_ms('asr_final', 'turn_end_detected'),
                            'salesbrain': trace.delta_ms('salesbrain_started', 'salesbrain_finished'),
                            'suggestion_persist': trace.delta_ms('salesbrain_finished', 'suggestion_persisted'),
                        },
                    },
                }
                await hub.publish_suggestion(call_id=self.call_id, company_id=self.company_id, payload=push_payload)
                trace.mark('ws_send_completed')
            # Sprint 2 ended at "Suggestion persisted"; Sprint 3A/ADR-051 add the
            # actual push above, but `t_ui_rendered`/`wallclock_rsl_estimate_ms`/
            # `server_render_ack_latency_ms` still stay unmarked/NULL here — those
            # are only ever set later, out of band, by the browser's own
            # POST /api/suggestions/{id}/render-ack (docs/DECISIONS.md ADR-048/051).
            # Marking them here would silently manufacture a fake RSL number,
            # exactly what the explicit "never call internal latency real RSL"
            # requirement forbids.
            row = build_latency_trace_row(
                trace, company_id=self.company_id, call_id=self.call_id,
                turn_id=result.get('turn_id', ''), trace_id=trace_id, speaker=turn_event.speaker,
                asr_provider=self.asr_provider_name, is_synthetic=self.is_synthetic,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()

    def diagnostics_summary(self) -> dict:
        return self.session.diagnostics_summary()
