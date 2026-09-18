"""Provider-Ready Gate: secrets resolution seam (app/secrets.py)."""
import pytest

from app.secrets import EnvSecretsProvider, get_secrets_provider, redact_secret


def test_env_provider_reads_and_defaults(monkeypatch):
    monkeypatch.setenv('REPLICA_TEST_SECRET', 'shhh')
    provider = EnvSecretsProvider()
    assert provider.get('REPLICA_TEST_SECRET') == 'shhh'
    assert provider.get('REPLICA_TEST_SECRET_MISSING') is None
    assert provider.get('REPLICA_TEST_SECRET_MISSING', 'fallback') == 'fallback'


def test_get_secrets_provider_defaults_to_env(monkeypatch):
    monkeypatch.delenv('REPLICA_SECRETS_BACKEND', raising=False)
    get_secrets_provider.cache_clear()
    provider = get_secrets_provider()
    assert isinstance(provider, EnvSecretsProvider)
    get_secrets_provider.cache_clear()


def test_unimplemented_backend_fails_loudly_not_silently(monkeypatch):
    monkeypatch.setenv('REPLICA_SECRETS_BACKEND', 'vault')
    get_secrets_provider.cache_clear()
    provider = get_secrets_provider()
    with pytest.raises(NotImplementedError):
        provider.get('ANYTHING')
    get_secrets_provider.cache_clear()


def test_redact_secret_never_leaks_short_values():
    assert redact_secret(None) == '<empty>'
    assert redact_secret('') == '<empty>'
    assert redact_secret('abc123xyz') == '*****3xyz'
    short = redact_secret('ab')
    assert 'ab' not in short or short.count('*') >= 4
