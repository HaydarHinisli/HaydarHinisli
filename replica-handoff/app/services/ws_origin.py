"""WebSocket Origin allowlist for browser-facing endpoints (Fix-Sprint after
Sprint 3A, docs/DECISIONS.md ADR-051): `/ws/live/{call_id}`'s first-message JWT
auth proves WHO is connecting; this proves WHERE the connecting page is allowed
to be served from — defending against a stolen/leaked JWT being replayed from an
unexpected page, on top of (not instead of) the JWT check.

Configured via `REPLICA_ALLOWED_WS_ORIGINS` (comma-separated). Outside local dev,
an unset/empty allowlist means NOTHING is allowed — fail closed, never "allow
everything" — a real deployment MUST explicitly configure its actual origin(s)
before the live-push endpoint is reachable from the public internet. Local dev
allows a missing `Origin` header/unset allowlist through unchecked, matching how
`app/streaming/media_stream_security.is_secure_transport()` also only gates wss
in production — local dev has no real reverse-proxy/origin setup to validate
against. Unlike that check (which gates on `== 'production'` specifically), this
one is deliberately broader — it gates on anything that ISN'T `'local'` — since
the user explicitly asked for both `production` and `staging` to be covered, and
a stricter default here costs nothing (an operator who names a third environment
value must configure the allowlist too, which is the safer failure mode).
"""
from __future__ import annotations


def parse_allowed_origins(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(',') if origin.strip()]


def is_allowed_origin(origin: str | None, *, env: str, allowed_origins: list[str]) -> bool:
    if env == 'local':
        return True
    if not origin:
        return False
    return origin in allowed_origins
