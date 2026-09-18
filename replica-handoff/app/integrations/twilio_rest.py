"""Twilio REST API client factory (Sprint 3A, docs/DECISIONS.md ADR-049).

Not used by any endpoint yet — REPLICA today only RECEIVES Twilio webhooks and
Media Streams, it does not yet call Twilio's REST API to originate/manage calls.
This factory exists so that when that need arrives (e.g. placing an outbound call,
querying a Call resource), the EU region/edge configuration is already wired
through a single seam instead of a scattered, easy-to-forget `region=`/`edge=`
kwarg at each call site.

The Twilio Python SDK's own `Client(...)` defaults to the `us1` region/edge when
`region`/`edge` are omitted — exactly the silent US1 fallback the pilot's EU data
residency requirement forbids. `get_twilio_rest_client()` therefore REFUSES to
construct a client unless both `TWILIO_REGION`/`TWILIO_EDGE` are explicitly
configured (defaults are already `ie1`/`dublin`, see app/config.py), rather than
ever calling `Client(sid, token)` without them and inheriting the SDK's own
default silently.
"""
from __future__ import annotations
from twilio.rest import Client

from ..config import get_settings


def status() -> dict:
    settings = get_settings()
    return {
        'provider': 'twilio',
        'connected': bool(settings.twilio_account_sid and settings.twilio_auth_token),
        'region': settings.twilio_region,
        'edge': settings.twilio_edge,
    }


def get_twilio_rest_client() -> Client:
    """Raises ValueError if account credentials or region/edge are not explicitly
    configured — fail-closed, consistent with this codebase's other secrets/config
    resolution (e.g. app/secrets.py, app/webhooks/security.py), never a silent
    fallback to the Twilio SDK's own us1 default."""
    settings = get_settings()
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        raise ValueError('Twilio account_sid/auth_token are not configured.')
    if not settings.twilio_region or not settings.twilio_edge:
        raise ValueError(
            'TWILIO_REGION/TWILIO_EDGE must be explicitly configured (pilot default: ie1/dublin) — '
            'refusing to construct a client that would silently fall back to the Twilio SDK\'s own us1 default.'
        )
    return Client(settings.twilio_account_sid, settings.twilio_auth_token, region=settings.twilio_region, edge=settings.twilio_edge)
