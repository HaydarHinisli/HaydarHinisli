"""Fix-Sprint (docs/DECISIONS.md ADR-051): pure NTP-style clock-sync estimation."""
from app.services.clock_sync import ClockSyncSample, estimate_clock_sync


def test_empty_samples_returns_none():
    assert estimate_clock_sync([]) is None


def test_perfectly_synced_clocks_zero_offset_and_rtt():
    # t1=0 client sends, t2=10 server receives, t3=10 server replies instantly,
    # t4=20 client receives — 20ms symmetric RTT, no clock offset at all.
    sample = ClockSyncSample(t1_client_send_ms=0, t2_server_recv_ms=10, t3_server_send_ms=10, t4_client_recv_ms=20)
    result = estimate_clock_sync([sample])
    assert result['offset_ms'] == 0
    assert result['rtt_ms'] == 20
    assert result['uncertainty_ms'] == 10  # half the single sample's RTT


def test_detects_a_known_positive_offset():
    # Server clock is 100ms ahead of the client's. Client sends at client-t=0
    # (server sees 100), server replies at client-equivalent-t=10 (server clock
    # 110), client receives at client-t=20. Symmetric 20ms RTT.
    sample = ClockSyncSample(t1_client_send_ms=0, t2_server_recv_ms=110, t3_server_send_ms=110, t4_client_recv_ms=20)
    result = estimate_clock_sync([sample])
    assert result['offset_ms'] == 100
    assert result['rtt_ms'] == 20


def test_picks_the_lowest_rtt_sample_as_primary_estimate():
    noisy = ClockSyncSample(t1_client_send_ms=0, t2_server_recv_ms=50, t3_server_send_ms=50, t4_client_recv_ms=100)  # 100ms RTT
    clean = ClockSyncSample(t1_client_send_ms=200, t2_server_recv_ms=205, t3_server_send_ms=205, t4_client_recv_ms=210)  # 10ms RTT
    result = estimate_clock_sync([noisy, clean])
    assert result['rtt_ms'] == 10
    assert result['offset_ms'] == 0  # the clean sample's true offset


def test_uncertainty_reflects_spread_across_multiple_samples():
    a = ClockSyncSample(t1_client_send_ms=0, t2_server_recv_ms=10, t3_server_send_ms=10, t4_client_recv_ms=20)  # offset 0
    b = ClockSyncSample(t1_client_send_ms=100, t2_server_recv_ms=130, t3_server_send_ms=130, t4_client_recv_ms=120)  # offset 20
    result = estimate_clock_sync([a, b])
    assert result['uncertainty_ms'] == 10  # (20 - 0) / 2
