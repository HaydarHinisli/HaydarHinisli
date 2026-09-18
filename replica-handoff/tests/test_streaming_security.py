"""Sprint 2 requirement 1: Twilio Media Streams WebSocket handshake security."""
from starlette.datastructures import URL, Headers, QueryParams
from starlette.websockets import WebSocket

from app.streaming.media_stream_security import is_secure_transport, verify_media_stream_signature
from app.webhooks.security import compute_twilio_signature

TOKEN = 'test-media-token'


class _FakeWebSocket:
    """Minimal stand-in exposing exactly the attributes
    media_stream_security.py reads, so these pure functions can be unit-tested
    without spinning up a real WS connection (the full-stack version is exercised
    in tests/test_streaming_pipeline_e2e.py)."""
    def __init__(self, *, url: str, headers: dict[str, str]):
        self.url = URL(url)
        self.headers = Headers(headers)
        self.query_params = QueryParams(self.url.query)


def test_verify_media_stream_signature_accepts_valid_signature():
    url = 'http://127.0.0.1:8000/ws/twilio-media'
    sig = compute_twilio_signature(url, {}, TOKEN)
    ws = _FakeWebSocket(url='ws://testserver/ws/twilio-media', headers={'x-twilio-signature': sig})
    assert verify_media_stream_signature(ws, auth_token=TOKEN, public_base_url='http://127.0.0.1:8000')


def test_verify_media_stream_signature_rejects_missing_signature():
    ws = _FakeWebSocket(url='ws://testserver/ws/twilio-media', headers={})
    assert not verify_media_stream_signature(ws, auth_token=TOKEN, public_base_url='http://127.0.0.1:8000')


def test_verify_media_stream_signature_rejects_wrong_signature():
    ws = _FakeWebSocket(url='ws://testserver/ws/twilio-media', headers={'x-twilio-signature': 'wrong=='})
    assert not verify_media_stream_signature(ws, auth_token=TOKEN, public_base_url='http://127.0.0.1:8000')


def test_verify_media_stream_signature_fails_closed_without_auth_token():
    url = 'http://127.0.0.1:8000/ws/twilio-media'
    sig = compute_twilio_signature(url, {}, TOKEN)
    ws = _FakeWebSocket(url='ws://testserver/ws/twilio-media', headers={'x-twilio-signature': sig})
    assert not verify_media_stream_signature(ws, auth_token=None, public_base_url='http://127.0.0.1:8000')


def test_verify_media_stream_signature_covers_query_string():
    url_with_query = 'http://127.0.0.1:8000/ws/twilio-media?tenant=acme'
    sig = compute_twilio_signature(url_with_query, {'tenant': 'acme'}, TOKEN)
    ws = _FakeWebSocket(url='ws://testserver/ws/twilio-media?tenant=acme', headers={'x-twilio-signature': sig})
    assert verify_media_stream_signature(ws, auth_token=TOKEN, public_base_url='http://127.0.0.1:8000')

    # tampering the query string after signing must invalidate it
    ws_tampered = _FakeWebSocket(url='ws://testserver/ws/twilio-media?tenant=evil', headers={'x-twilio-signature': sig})
    assert not verify_media_stream_signature(ws_tampered, auth_token=TOKEN, public_base_url='http://127.0.0.1:8000')


def test_is_secure_transport_true_for_wss_scheme():
    ws = _FakeWebSocket(url='wss://replica.example.com/ws/twilio-media', headers={})
    assert is_secure_transport(ws)


def test_is_secure_transport_false_for_plain_ws_scheme_without_forwarded_header():
    ws = _FakeWebSocket(url='ws://replica.example.com/ws/twilio-media', headers={})
    assert not is_secure_transport(ws)


def test_is_secure_transport_respects_x_forwarded_proto_behind_reverse_proxy():
    # Reverse proxy terminates TLS and connects to REPLICA over plain ws, but tells
    # us the original connection was https via X-Forwarded-Proto.
    ws = _FakeWebSocket(url='ws://127.0.0.1:8000/ws/twilio-media', headers={'x-forwarded-proto': 'https'})
    assert is_secure_transport(ws)


def test_is_secure_transport_forwarded_proto_can_also_say_insecure():
    ws = _FakeWebSocket(url='wss://127.0.0.1:8000/ws/twilio-media', headers={'x-forwarded-proto': 'http'})
    assert not is_secure_transport(ws)
