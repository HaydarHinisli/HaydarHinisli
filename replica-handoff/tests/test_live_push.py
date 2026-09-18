"""Sprint 3A (docs/DECISIONS.md ADR-048): LiveSuggestionHub unit tests — tenant
isolation, sync-on-connect, and the guidance_hint UI-label mapping — independent
of the HTTP/WebSocket layer.
"""
import asyncio

from app.services.live_push import LiveSuggestionHub, guidance_hint

run = asyncio.run


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.raise_on_send = False

    async def send_json(self, data: dict) -> None:
        if self.raise_on_send:
            raise RuntimeError('connection is gone')
        self.sent.append(data)


def test_guidance_hint_maps_known_strategies():
    assert guidance_hint('reestablish_value_before_price') == 'Preis noch nicht verteidigen'
    assert guidance_hint('discover_buying_criteria') == 'weiterfragen'
    assert guidance_hint('separate_reflex_from_rejection') == 'nicht argumentieren'


def test_guidance_hint_is_none_for_unknown_or_missing_strategy():
    assert guidance_hint('some_future_strategy_not_in_the_table') is None
    assert guidance_hint(None) is None


def test_publish_delivers_only_to_subscribers_of_the_same_call():
    hub = LiveSuggestionHub()
    ws_call_1 = _FakeWebSocket()
    ws_call_2 = _FakeWebSocket()
    hub.register(call_id=1, company_id=10, user_id=1, websocket=ws_call_1)
    hub.register(call_id=2, company_id=10, user_id=1, websocket=ws_call_2)

    result = run(hub.publish_suggestion(call_id=1, company_id=10, payload={'suggestion_id': 99}))

    assert result == {'delivered_to': 1}
    assert ws_call_1.sent == [{'type': 'suggestion', 'suggestion_id': 99}]
    assert ws_call_2.sent == []


def test_publish_never_delivers_across_tenants_even_for_the_same_call_id():
    """Structurally unreachable via the real WS endpoint (it always registers
    with the subscriber's OWN verified company_id) — this proves the hub's own
    defense-in-depth check independently of that caller discipline."""
    hub = LiveSuggestionHub()
    ws = _FakeWebSocket()
    hub.register(call_id=1, company_id=10, user_id=1, websocket=ws)

    result = run(hub.publish_suggestion(call_id=1, company_id=999, payload={'suggestion_id': 1}))

    assert result == {'delivered_to': 0}
    assert ws.sent == []


def test_publish_drops_a_dead_subscriber_without_affecting_others():
    hub = LiveSuggestionHub()
    dead = _FakeWebSocket()
    dead.raise_on_send = True
    alive = _FakeWebSocket()
    hub.register(call_id=1, company_id=10, user_id=1, websocket=dead)
    hub.register(call_id=1, company_id=10, user_id=2, websocket=alive)

    result = run(hub.publish_suggestion(call_id=1, company_id=10, payload={'suggestion_id': 5}))

    assert result == {'delivered_to': 1}
    assert alive.sent == [{'type': 'suggestion', 'suggestion_id': 5}]
    assert hub.subscriber_count(1) == 1  # the dead one was unregistered


def test_last_payload_is_available_for_sync_on_connect_and_updates_per_call():
    hub = LiveSuggestionHub()
    assert hub.last_payload(1) is None
    run(hub.publish_suggestion(call_id=1, company_id=10, payload={'suggestion_id': 1}))
    assert hub.last_payload(1) == {'suggestion_id': 1}
    run(hub.publish_suggestion(call_id=1, company_id=10, payload={'suggestion_id': 2}))
    assert hub.last_payload(1) == {'suggestion_id': 2}  # latest wins, no backlog
    assert hub.last_payload(2) is None  # a different call_id is unaffected


def test_unregister_removes_subscriber_and_empty_call_entry():
    hub = LiveSuggestionHub()
    ws = _FakeWebSocket()
    sub = hub.register(call_id=1, company_id=10, user_id=1, websocket=ws)
    assert hub.subscriber_count(1) == 1
    hub.unregister(sub)
    assert hub.subscriber_count(1) == 0
    hub.unregister(sub)  # idempotent — unregistering twice must not raise
