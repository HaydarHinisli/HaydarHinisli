"""Browser<->server clock-sync preparation (Fix-Sprint after Sprint 3A,
docs/DECISIONS.md ADR-051).

Sprint 3A's `wallclock_rsl_estimate_ms` compares a wall-clock timestamp read by
the browser against one read by this server — two machines with no shared clock,
so the delta is only ever an ESTIMATE, with an error bounded by however far the
two clocks' wall-clocks actually differ (their "offset") plus any error from that
offset itself being estimated over an imperfect network.

This module implements the classic NTP four-timestamp offset/RTT calculation —
`t1` client sends a ping, `t2` server receives it, `t3` server sends the pong,
`t4` client receives the pong:

    offset = ((t2 - t1) + (t3 - t4)) / 2   # positive: server clock ahead of client
    rtt    = (t4 - t1) - (t3 - t2)          # round-trip time, symmetric-network assumption

All four timestamps must be expressed in the SAME unit (this codebase uses
milliseconds throughout, matching `Date.now()`/`performance.now()`); `t1`/`t4` are
the client's own clock, `t2`/`t3` are the server's.

This is preparation only — per explicit instruction, nothing in this codebase yet
uses `estimate_clock_sync()`'s output to correct `wallclock_rsl_estimate_ms`. It
is computed and persisted (`TurnLatencyTrace.clock_offset_estimate_ms`/
`clock_rtt_estimate_ms`/`clock_uncertainty_ms`) purely so a later sprint has the
data to build a genuinely clock-corrected, uncertainty-bounded RSL estimate.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ClockSyncSample:
    """One ping/pong round trip, all four timestamps in milliseconds."""
    t1_client_send_ms: float
    t2_server_recv_ms: float
    t3_server_send_ms: float
    t4_client_recv_ms: float


def _offset_and_rtt(sample: ClockSyncSample) -> tuple[float, float]:
    offset = ((sample.t2_server_recv_ms - sample.t1_client_send_ms) + (sample.t3_server_send_ms - sample.t4_client_recv_ms)) / 2
    rtt = (sample.t4_client_recv_ms - sample.t1_client_send_ms) - (sample.t3_server_send_ms - sample.t2_server_recv_ms)
    return offset, rtt


def estimate_clock_sync(samples: list[ClockSyncSample]) -> dict | None:
    """Returns {'offset_ms', 'rtt_ms', 'uncertainty_ms'}, or None for an empty
    sample list. Per standard NTP practice, the sample with the LOWEST RTT is
    used as the primary estimate (a lower RTT means less asymmetry-induced
    error in the offset calculation); `uncertainty_ms` is half the spread across
    all samples' offsets (or half the chosen sample's own RTT when only one
    sample exists, since RTT itself bounds how wrong a single-sample offset
    estimate can be)."""
    if not samples:
        return None
    pairs = [_offset_and_rtt(s) for s in samples]
    offsets = [offset for offset, _ in pairs]
    best_index = min(range(len(pairs)), key=lambda i: pairs[i][1])
    best_offset, best_rtt = pairs[best_index]
    if len(pairs) > 1:
        uncertainty = (max(offsets) - min(offsets)) / 2
    else:
        uncertainty = best_rtt / 2
    return {'offset_ms': best_offset, 'rtt_ms': best_rtt, 'uncertainty_ms': uncertainty}
