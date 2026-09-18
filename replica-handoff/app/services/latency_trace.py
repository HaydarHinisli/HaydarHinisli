"""End-to-end pipeline timing (Sprint 2, docs/DECISIONS.md ADR-041).

`LatencyTrace` records a monotonic + wall-clock pair the first time each named stage
is marked. Monotonic (`time.monotonic()`) is used for every duration/delta
computation — it cannot go backwards or jump from NTP/system clock adjustments,
which a wall-clock reading can. Wall-clock (`datetime.utcnow()`) is stored purely for
audit/tracing correlation across systems and logs, per the explicit requirement to
keep both; it is never used for latency math.

Stage names match docs/ARCHITECTURE.md §8 / the Sprint 2 requirements, refined in
Sprint 3A/ADR-051: audio_received, asr_interim, asr_final, turn_end_detected,
salesbrain_started, salesbrain_finished, suggestion_persisted, push_enqueued (the
moment the pipeline hands the Suggestion to LiveSuggestionHub — renamed from
suggestion_pushed), ws_send_completed (once the actual WebSocket send(s)
finished — separates hub-handoff latency from network/event-loop latency),
ui_rendered (stays unmarked here — only ever set out of band by a real
Render-ACK, see app/services/turn_pipeline and app/main.py's render-ack endpoint).
`provider_endpoint_detected` (Sprint 2B) is an additional, comparison-only stage —
see docs/DECISIONS.md ADR-046.

`RUNTIME_BOOT_ID` (follow-up hardening after ADR-051): a random id generated once
per process start, stamped onto `TurnLatencyTrace.t_turn_end_detected_monotonic_
runtime_id` alongside the raw monotonic value. `time.monotonic()`'s reference
point is documented by Python itself as undefined outside the process that read
it; comparing a value captured in one process/host against `time.monotonic()`
read later in a DIFFERENT process (a restart, a host change, or — in a
misconfigured multi-instance deployment — a different instance entirely) can
silently produce a meaningless or wildly wrong delta. Comparing `RUNTIME_BOOT_ID`
first (see app/main.py's render-ack endpoint) is how comparability is actually
VERIFIED rather than assumed: a mismatch means "not safely comparable", and the
derived `server_render_ack_latency_ms` is then never computed, not estimated.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from ..models import TurnLatencyTrace

STAGES = (
    'audio_received', 'asr_interim', 'asr_final', 'turn_end_detected',
    'provider_endpoint_detected', 'salesbrain_started', 'salesbrain_finished',
    'suggestion_persisted', 'push_enqueued', 'ws_send_completed', 'ui_rendered',
)

# Generated once, at first import of this module (i.e. once per process
# lifetime) — see the module docstring above for what this guards against.
RUNTIME_BOOT_ID = uuid.uuid4().hex


@dataclass(frozen=True)
class _Stamp:
    monotonic: float
    wallclock: datetime


@dataclass
class LatencyTrace:
    _stamps: dict[str, _Stamp] = field(default_factory=dict)

    def mark(self, stage: str, *, at_monotonic: float | None = None) -> None:
        """Idempotent per stage: only the FIRST mark for a given stage is kept (an
        interim transcript may fire many times; only the earliest counts as
        `asr_interim` for latency purposes)."""
        if stage in self._stamps:
            return
        self._stamps[stage] = _Stamp(
            monotonic=time.monotonic() if at_monotonic is None else at_monotonic,
            wallclock=datetime.utcnow(),
        )

    def wallclock(self, stage: str) -> datetime | None:
        stamp = self._stamps.get(stage)
        return stamp.wallclock if stamp else None

    def monotonic_at(self, stage: str) -> float | None:
        stamp = self._stamps.get(stage)
        return stamp.monotonic if stamp else None

    def delta_ms(self, start_stage: str, end_stage: str) -> float | None:
        start = self._stamps.get(start_stage)
        end = self._stamps.get(end_stage)
        if start is None or end is None:
            return None
        return (end.monotonic - start.monotonic) * 1000.0


def build_latency_trace_row(
    trace: LatencyTrace, *, company_id: int, call_id: int, turn_id: str, trace_id: str | None, speaker: str,
    asr_provider: str = 'simulated', is_synthetic: bool = True,
) -> TurnLatencyTrace:
    """`asr_provider`/`is_synthetic` (Sprint 2B, ADR-045): callers MUST pass the
    real provider name and `is_synthetic=False` once real-provider verification is
    underway — the defaults here deliberately assume the synthetic/simulated case,
    so a caller that forgets to pass them gets an honestly-labelled dev row, never a
    silently-mislabelled "real" one."""
    return TurnLatencyTrace(
        company_id=company_id, call_id=call_id, turn_id=turn_id, trace_id=trace_id, speaker=speaker,
        asr_provider=asr_provider, is_synthetic=is_synthetic,
        t_audio_received_at=trace.wallclock('audio_received'),
        t_asr_interim_at=trace.wallclock('asr_interim'),
        t_asr_final_at=trace.wallclock('asr_final'),
        t_turn_end_detected_at=trace.wallclock('turn_end_detected'),
        # ADR-051: the one deliberately-persisted raw monotonic value — see
        # TurnLatencyTrace's class docstring — needed later to compute
        # server_render_ack_latency_ms when the Render-ACK HTTP request arrives.
        # Stamped with RUNTIME_BOOT_ID so that later comparison can be VERIFIED
        # rather than assumed — see this module's docstring.
        t_turn_end_detected_monotonic=trace.monotonic_at('turn_end_detected'),
        t_turn_end_detected_monotonic_runtime_id=(
            RUNTIME_BOOT_ID if trace.monotonic_at('turn_end_detected') is not None else None
        ),
        t_provider_endpoint_detected_at=trace.wallclock('provider_endpoint_detected'),
        t_salesbrain_started_at=trace.wallclock('salesbrain_started'),
        t_salesbrain_finished_at=trace.wallclock('salesbrain_finished'),
        t_suggestion_persisted_at=trace.wallclock('suggestion_persisted'),
        t_push_enqueued_at=trace.wallclock('push_enqueued'),
        t_ws_send_completed_at=trace.wallclock('ws_send_completed'),
        t_ui_rendered_at=trace.wallclock('ui_rendered'),
        audio_to_interim_ms=trace.delta_ms('audio_received', 'asr_interim'),
        audio_to_final_ms=trace.delta_ms('audio_received', 'asr_final'),
        turn_detection_latency_ms=trace.delta_ms('asr_final', 'turn_end_detected'),
        provider_endpoint_vs_turn_end_ms=trace.delta_ms('provider_endpoint_detected', 'turn_end_detected'),
        # Internal engine latency ONLY (docs/DECISIONS.md ADR-021/022) — never call
        # this RSL. wallclock_rsl_estimate_ms/server_render_ack_latency_ms (set
        # later, out of band, by the Render-ACK endpoint) are the RSL-related figures.
        salesbrain_latency_ms=trace.delta_ms('salesbrain_started', 'salesbrain_finished'),
        suggestion_persist_latency_ms=trace.delta_ms('salesbrain_finished', 'suggestion_persisted'),
        suggestion_push_latency_ms=trace.delta_ms('suggestion_persisted', 'push_enqueued'),
        ws_send_latency_ms=trace.delta_ms('push_enqueued', 'ws_send_completed'),
        wallclock_rsl_estimate_ms=trace.delta_ms('turn_end_detected', 'ui_rendered'),
    )
