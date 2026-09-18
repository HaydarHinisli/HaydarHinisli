"""Sprint 2B requirement 1: explicit, injectable speaker-role mapping — inbound/
outbound must never be silently hardcoded as prospect/seller."""
from app.streaming.media_stream_session import INBOUND, OUTBOUND
from app.streaming.speaker_mapping import OutboundSalesFlowResolver, get_default_speaker_role_resolver


def test_outbound_sales_flow_resolver_maps_inbound_to_prospect():
    resolver = OutboundSalesFlowResolver()
    assert resolver.resolve(INBOUND) == 'prospect'


def test_outbound_sales_flow_resolver_maps_outbound_to_seller():
    resolver = OutboundSalesFlowResolver()
    assert resolver.resolve(OUTBOUND) == 'seller'


def test_outbound_sales_flow_resolver_passes_through_unknown_track_names():
    resolver = OutboundSalesFlowResolver()
    assert resolver.resolve('sideband') == 'sideband'  # never guessed as prospect/seller


def test_default_resolver_factory_returns_outbound_sales_flow_resolver():
    resolver = get_default_speaker_role_resolver()
    assert isinstance(resolver, OutboundSalesFlowResolver)
    assert resolver.TOPOLOGY_NAME == 'outbound_sales_flow_v1'


def test_turn_detector_accepts_an_injected_custom_resolver():
    from app.streaming.turn_detector import TurnDetector

    class ReversedResolver:
        def resolve(self, track):
            return 'seller' if track == INBOUND else 'prospect'

    td = TurnDetector(speaker_role_resolver=ReversedResolver())
    td.on_vad_update(INBOUND, True, now_monotonic=0.0)
    td.on_vad_update(INBOUND, False, now_monotonic=1.0)
    turn = td.on_turn_ended(INBOUND, 'hallo', now_monotonic=1.0)
    assert turn.speaker == 'seller'  # honors the injected mapping, not the default
