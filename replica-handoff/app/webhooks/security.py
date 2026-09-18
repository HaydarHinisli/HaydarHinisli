"""Provider webhook signature verification.

Twilio signs every webhook request with an X-Twilio-Signature header: HMAC-SHA1 over
the full request URL (protocol through the end of the query string) followed by each
POST parameter's key+value (sorted by key, concatenated with no separator), keyed with
the account's Auth Token, base64-encoded. See
https://www.twilio.com/docs/usage/security#validating-requests (docs/PROVIDER_REFERENCES.md).

The actual cryptographic check (docs/DECISIONS.md ADR-036) is delegated to Twilio's
own, officially maintained `twilio.request_validator.RequestValidator` rather than a
hand-rolled HMAC implementation — it already handles edge cases REPLICA would
otherwise have to independently track and keep in sync with Twilio's own algorithm
(port-inclusive vs. port-stripped URL variants, multi-value POST params, ...).
REPLICA's own responsibility, kept entirely in app/main.py's `twilio_call_status()`,
stays: resolving the right secret, constructing the correct public-facing request URL
(protocol, host, path AND query string — the validator does not do this for you; a
URL missing the query string, or reconstructed from the wrong base, silently produces
a mismatched signature) accounting for a TLS-terminating reverse proxy, tenant/
provider context, logging/audit, and fail-closed error handling.

This is the ONLY authentication a webhook endpoint gets — Twilio cannot present one of
our bearer tokens — so verification failure must fail closed (403), never fall back to
"process anyway". See docs/DECISIONS.md ADR-029/ADR-036.
"""
from __future__ import annotations
from twilio.request_validator import RequestValidator


def compute_twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """Test/debugging helper — delegates to Twilio's own algorithm so fixtures in
    this codebase can never silently drift from what verify_twilio_signature() below
    actually checks."""
    return RequestValidator(auth_token).compute_signature(url, params)


def verify_twilio_signature(url: str, params: dict[str, str], signature: str | None, auth_token: str | None) -> bool:
    if not signature or not auth_token:
        return False
    return RequestValidator(auth_token).validate(url, params, signature)
