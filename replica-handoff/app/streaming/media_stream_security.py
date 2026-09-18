"""Twilio Media Streams WebSocket security (Sprint 2, closing the gap the user
flagged explicitly: the existing HTTP webhook signature check, ADR-029/036, does not
cover the new WebSocket ingestion path at all).

Two independent checks, both fail-closed and both evaluated BEFORE
`websocket.accept()` — an unauthenticated or insecure connection is refused at the
handshake, never accepted and then dropped:

1. `verify_media_stream_signature()`: Twilio signs the Media Streams connection
   request the same way it signs webhooks (X-Twilio-Signature, see
   app/webhooks/security.py) — reusing the exact same official RequestValidator.
   Documented assumption (this environment cannot make a live Twilio connection to
   confirm wire behavior against a real account): per Twilio's own guidance, a
   WebSocket upgrade request has no POST body, so the parameters to validate are the
   request's query-string parameters (empty dict if none) rather than form fields.
   This MUST be confirmed against a real Twilio Media Streams connection before pilot
   go-live — flagged explicitly here and in the final report rather than silently
   assumed correct.

2. `is_secure_transport()`: the production media stream must run over `wss`. Behind
   a TLS-terminating reverse proxy, `websocket.url.scheme` reflects the proxy's own
   (often plain `ws`) connection to REPLICA, not what the browser/Twilio actually
   used — so `X-Forwarded-Proto` is checked first when present, matching the same
   reverse-proxy caveat already documented for HTTP webhooks (ADR-029/036).
   Enforcement itself is gated on `REPLICA_ENV=production`, since local dev/test runs
   legitimately use plain `ws://` with no TLS-terminating proxy in front of them at
   all — the same environment flag already used elsewhere in this codebase (e.g.
   `GET /api/health`), not a new concept.
"""
from __future__ import annotations
from starlette.websockets import WebSocket

from ..webhooks.security import verify_twilio_signature


def verify_media_stream_signature(websocket: WebSocket, *, auth_token: str | None, public_base_url: str) -> bool:
    signature = websocket.headers.get('x-twilio-signature')
    query = f'?{websocket.url.query}' if websocket.url.query else ''
    url = f'{public_base_url.rstrip("/")}{websocket.url.path}{query}'
    params = dict(websocket.query_params)
    return verify_twilio_signature(url, params, signature, auth_token)


def is_secure_transport(websocket: WebSocket) -> bool:
    forwarded_proto = websocket.headers.get('x-forwarded-proto', '').strip().lower()
    if forwarded_proto:
        return forwarded_proto == 'https'
    return websocket.url.scheme == 'wss'
