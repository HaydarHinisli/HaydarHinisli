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
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
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


def create_voice_access_token(identity: str, ttl_seconds: int = 3600) -> dict:
    """ADR-060/061: mints a short-lived Twilio Access Token carrying a VoiceGrant,
    so the browser (Twilio Voice JS SDK) can register a `Device` and place an
    outbound call via `device.connect()` — the browser-calling equivalent of
    `get_twilio_rest_client()` above, which places calls server-side via REST
    instead. Deliberately uses TWILIO_API_KEY_SID/SECRET, never
    TWILIO_ACCOUNT_SID/AUTH_TOKEN — an Access Token signed with the main Auth
    Token would work too, but Twilio's own guidance is to keep API Keys and the
    Auth Token on separate, independently revocable credentials; this project's
    Auth Token is also already relied on elsewhere purely as a webhook-signature
    secret (docs/DECISIONS.md ADR-036), so reusing it here would blur that
    boundary. Fails closed (ValueError) if any required setting is missing, same
    posture as `get_twilio_rest_client()` above.

    Fix (ADR-061): the initial ADR-060 implementation omitted `region=` on the
    `AccessToken` — verified directly against the installed Twilio SDK's own
    source (`AccessToken._generate_headers()`) that this parameter is NOT a
    no-op: it sets the JWT's `twr` (Twilio Region) header claim, which is how
    Twilio's signaling infrastructure is told which region to route through.
    Without it, the token carried no region preference at all, silently
    defeating the exact EU-data-residency guarantee `get_twilio_rest_client()`
    above already enforces for REST calls — so this now fails closed on a
    missing TWILIO_REGION/TWILIO_EDGE exactly like that function does, rather
    than letting the Voice SDK path be the one place this account's EU
    residency requirement was silently skippable. `edge` cannot be embedded in
    the Access Token itself (there is no such JWT claim) — Twilio's Voice JS
    SDK takes it as a separate `Device` constructor option instead, so it is
    returned here for the caller (the `/api/voice/access-token` endpoint) to
    hand to the browser alongside the token, keeping `TWILIO_EDGE` as the one
    source of truth rather than a value hardcoded a second time in JavaScript.
    """
    settings = get_settings()
    if not settings.twilio_account_sid or not settings.twilio_api_key_sid or not settings.twilio_api_key_secret:
        raise ValueError('TWILIO_ACCOUNT_SID/TWILIO_API_KEY_SID/TWILIO_API_KEY_SECRET are not all configured.')
    if not settings.twilio_twiml_app_sid:
        raise ValueError('TWILIO_TWIML_APP_SID is not configured.')
    if not settings.twilio_region or not settings.twilio_edge:
        raise ValueError(
            'TWILIO_REGION/TWILIO_EDGE must be explicitly configured (pilot default: ie1/dublin) — '
            'refusing to issue a Voice Access Token with no region preference at all.'
        )
    token = AccessToken(
        settings.twilio_account_sid, settings.twilio_api_key_sid, settings.twilio_api_key_secret,
        identity=identity, ttl=ttl_seconds, region=settings.twilio_region,
    )
    token.add_grant(VoiceGrant(outgoing_application_sid=settings.twilio_twiml_app_sid))
    return {'token': token.to_jwt(), 'region': settings.twilio_region, 'edge': settings.twilio_edge}
