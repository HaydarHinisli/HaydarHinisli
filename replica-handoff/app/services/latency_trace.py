"""End-to-end pipeline timing (Sprint 2, docs/DECISIONS.md ADR-041).

`LatencyTrace` records a monotonic + wall-clock pair the first time each named stage
is marked. Monotonic (`time.monotonic()`) is used for every duration/delta
computation — it cannot go backwards or jump from NTP/system clock adjustments,
which a wall-clock reading can. Wall-clock (`datetime.utcnow()`) is stored purely for
audit/tracing correlation across systems and logs, per the explicit requirement to
keep both; it is never used for latency math.

Stage names match docs/ARCHITECTURE.md §8 / the Sprint 2 requirements exactly:
audio_received, asr_interim, asr_final, turn_end_detected, salesbrain_started,
salesbrain_finished, suggestion_persisted, suggestion_pushed, ui_rendered (the last
one stays unmarked until Sprint 3 wires a real UI render acknowledgement).
`provider_endpoint_detected` (Sprint 2B) is an additional, comparison-only stage —
see docs/DECISIONS.md ADR-046.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime

from ..models import TurnLatencyTrace

STAGES = (
    'audio_received', 'asr_interim', 'asr_final', 'turn_end_detected',
    'provider_endpoint_detected', 'salesbrain_started', 'salesbrain_finished',
    'suggestion_persisted', 'suggestion_pushed', 'ui_rendered',
)


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
        t_provider_endpoint_detected_at=trace.wallclock('provider_endpoint_detected'),
        t_salesbrain_started_at=trace.wallclock('salesbrain_started'),
        t_salesbrain_finished_at=trace.wallclock('salesbrain_finished'),
        t_suggestion_persisted_at=trace.wallclock('suggestion_persisted'),
        t_suggestion_pushed_at=trace.wallclock('suggestion_pushed'),
        t_ui_rendered_at=trace.wallclock('ui_rendered'),
        audio_to_interim_ms=trace.delta_ms('audio_received', 'asr_interim'),
        audio_to_final_ms=trace.delta_ms('audio_received', 'asr_final'),
        turn_detection_latency_ms=trace.delta_ms('asr_final', 'turn_end_detected'),
        provider_endpoint_vs_turn_end_ms=trace.delta_ms('provider_endpoint_detected', 'turn_end_detected'),
        # Internal engine latency ONLY (docs/DECISIONS.md ADR-021/022) — never call
        # this RSL. Real RSL is real_rsl_ms below, and it alone is the product metric.
        salesbrain_latency_ms=trace.delta_ms('salesbrain_started', 'salesbrain_finished'),
        suggestion_persist_latency_ms=trace.delta_ms('salesbrain_finished', 'suggestion_persisted'),
        suggestion_push_latency_ms=trace.delta_ms('suggestion_persisted', 'suggestion_pushed'),
        real_rsl_ms=trace.delta_ms('turn_end_detected', 'ui_rendered'),
    )
