"""Secrets resolution seam (Provider-Ready Gate).

Today every secret (provider tokens, JWT signing key) is read from environment
variables via app/config.py's pydantic-settings Settings — fine for a single-tenant
pilot, but a real deployment needs a swap point to a managed secret store (Vault, AWS
Secrets Manager, GCP Secret Manager) without touching every call site. This module IS
that seam: get_secrets_provider() returns whichever backend REPLICA_SECRETS_BACKEND
selects. Only 'env' is implemented — the others raise a clear, honest
NotImplementedError rather than pretending to be production-ready vault integrations
this environment cannot actually exercise or verify (see docs/DECISIONS.md ADR-028).

Nothing about this module encrypts secrets at rest; it centralizes *where a secret's
value is fetched from* so that swap is one function, not a grep-and-replace across the
codebase, and centralizes redaction so a secret value never has to be interpolated
into a log/error message by hand at each call site.
"""
from __future__ import annotations
import os
from functools import lru_cache
from typing import Protocol


class SecretsProvider(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None: ...


class EnvSecretsProvider:
    """Default backend: reads from process environment variables — the same source
    app/config.py's Settings already reads from. This is the correct backend for
    local dev and the current single-tenant pilot; it is not itself a secret store."""

    def get(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)


class _UnimplementedBackend:
    """Placeholder for a real managed secret store. Raises rather than silently
    falling back to env, so a misconfigured REPLICA_SECRETS_BACKEND fails loudly at
    startup instead of quietly behaving like 'env' in production."""

    def __init__(self, backend_name: str):
        self._backend_name = backend_name

    def get(self, key: str, default: str | None = None) -> str | None:
        raise NotImplementedError(
            f'REPLICA_SECRETS_BACKEND="{self._backend_name}" is not implemented yet. '
            'Only "env" is available in this codebase today. Wiring a real backend '
            '(HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, ...) means '
            'implementing SecretsProvider.get() against that service\'s SDK here — '
            'see docs/DECISIONS.md ADR-028 — not silently falling back to env vars.'
        )


@lru_cache
def get_secrets_provider() -> SecretsProvider:
    backend = os.environ.get('REPLICA_SECRETS_BACKEND', 'env').strip().lower()
    if backend == 'env':
        return EnvSecretsProvider()
    return _UnimplementedBackend(backend)


def redact_secret(value: str | None, *, visible: int = 4) -> str:
    """Masks a secret for safe inclusion in a log line or error message: shows at
    most the last `visible` characters, everything else becomes '*'. Never returns
    the original value length exactly for very short secrets, to avoid leaking that
    a secret is e.g. a 4-character test string."""
    if not value:
        return '<empty>'
    if len(value) <= visible:
        return '*' * max(len(value), 6)
    return '*' * (len(value) - visible) + value[-visible:]
