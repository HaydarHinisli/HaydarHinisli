"""Provider webhook signature verification.

Twilio signs every webhook request with an X-Twilio-Signature header: HMAC-SHA1 over
the full request URL followed by each POST parameter's key+value (sorted by key,
concatenated with no separator), keyed with the account's Auth Token, base64-encoded.
See https://www.twilio.com/docs/usage/security#validating-requests (docs/PROVIDER_REFERENCES.md).

This is the ONLY authentication a webhook endpoint gets — Twilio cannot present one of
our bearer tokens — so verification failure must fail closed (403), never fall back to
"process anyway". See docs/DECISIONS.md ADR-029.
"""
from __future__ import annotations
import base64
import hashlib
import hmac


def compute_twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    data = url
    for key in sorted(params.keys()):
        data += f'{key}{params[key]}'
    digest = hmac.new(auth_token.encode('utf-8'), data.encode('utf-8'), hashlib.sha1).digest()
    return base64.b64encode(digest).decode('utf-8')


def verify_twilio_signature(url: str, params: dict[str, str], signature: str | None, auth_token: str | None) -> bool:
    if not signature or not auth_token:
        return False
    expected = compute_twilio_signature(url, params, auth_token)
    return hmac.compare_digest(expected, signature)
