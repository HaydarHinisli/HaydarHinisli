"""Password hashing and JWT session tokens.

Pilot-grade, not final production hardening: password hashing uses stdlib
hashlib.pbkdf2_hmac (no extra native dependency) rather than bcrypt/argon2, and
tokens are self-contained JWTs rather than server-side revocable sessions. Both are
documented, tracked gaps (see README "Produktionslücken" and docs/DECISIONS.md
ADR-018), not an oversight — full OAuth + a revocable session store is Sprint 2+ work.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os
import time
import uuid

import jwt

from ..config import get_settings

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return f'pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = encoded.split('$')
        if scheme != 'pbkdf2_sha256':
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, int(iterations))
    return hmac.compare_digest(candidate, expected)


def create_access_token(*, user_id: int, company_id: int | None, role: str) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        'sub': str(user_id),
        'company_id': company_id,
        'role': role,
        'iat': now,
        'exp': now + settings.replica_jwt_expires_minutes * 60,
    }
    return jwt.encode(payload, settings.replica_jwt_secret, algorithm='HS256')


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.replica_jwt_secret, algorithms=['HS256'])


VOICE_CALL_TICKET_PURPOSE = 'voice_call_ticket'
VOICE_CALL_TICKET_TTL_SECONDS = 300


def create_voice_call_ticket(*, call_id: int, company_id: int, user_id: int, ttl_seconds: int = VOICE_CALL_TICKET_TTL_SECONDS) -> dict:
    """Red-team hardening (docs/DECISIONS.md ADR-063, item 7/8): a real browser
    call's TwiML webhook (`POST /webhooks/twilio/voice-outbound`) is authenticated
    ONLY by Twilio's own signature — it never sees the seller's REPLICA bearer
    token, so it has no independent way to know which tenant/call the browser is
    ALLOWED to bind this call to. A raw `call_id` sent as a `device.connect()`
    custom parameter is attacker-controlled (an untrusted browser client) and MUST
    NOT be trusted directly (see `_resolve_call_for_media_stream()`'s doc comment).

    This ticket is a short-lived, REPLICA-signed (not Twilio-signed) JWT minted
    ONLY after `/api/voice/access-token` has independently verified tenant
    ownership and consent/policy for the requested `call_id` — it carries that
    already-verified `call_id`/`company_id` as signed claims. The browser cannot
    forge or alter one (it does not have `REPLICA_JWT_SECRET`), so whatever
    `call_id` the voice-outbound webhook ultimately trusts (decoded from this
    ticket, never a raw browser-supplied value) is guaranteed to be the exact one
    a real, authenticated, authorized tenant user was granted moments earlier.

    A distinct `purpose` claim (not reused from `create_access_token()`'s login
    tokens) means a stolen/leaked login session token could never be replayed
    here as if it were a voice ticket, and vice versa. Deliberately short-lived
    (5 minutes default) — long enough to place the call immediately after minting
    it, short enough to bound a leaked ticket's usable window; unrelated to the
    Twilio Access Token's own (longer) TTL, which covers the Device's REGISTRATION
    for the test call's duration, not this specific call-authorization artifact.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        'purpose': VOICE_CALL_TICKET_PURPOSE,
        'call_id': call_id,
        'company_id': company_id,
        'user_id': user_id,
        # docs/DECISIONS.md ADR-064 (red-team item 1): a unique id per MINTED
        # ticket, distinct from anything Twilio provides — this is what lets
        # the voice-outbound webhook tell "Twilio retried the exact same call
        # attempt" (same ticket jti + same Twilio CallSid — idempotent, must
        # proceed) apart from "this ticket is being reused to start an
        # independent second call" (same jti, a DIFFERENT CallSid — replay,
        # must fail closed). Signature/expiry alone cannot distinguish these:
        # both present an identical, still-valid, correctly-signed ticket.
        'jti': uuid.uuid4().hex,
        'iat': now,
        'exp': now + ttl_seconds,
    }
    ticket = jwt.encode(payload, settings.replica_jwt_secret, algorithm='HS256')
    return {'ticket': ticket, 'ttl_seconds': ttl_seconds}


def decode_voice_call_ticket(ticket: str) -> dict:
    """Raises jwt.InvalidTokenError (or a subclass, e.g. ExpiredSignatureError)
    on any invalid/expired/tampered/wrong-purpose ticket — callers must treat
    all of these identically: fail closed, never fall back to a raw/unverified
    call_id."""
    settings = get_settings()
    payload = jwt.decode(ticket, settings.replica_jwt_secret, algorithms=['HS256'])
    if payload.get('purpose') != VOICE_CALL_TICKET_PURPOSE:
        raise jwt.InvalidTokenError('Not a voice call ticket')
    return payload
