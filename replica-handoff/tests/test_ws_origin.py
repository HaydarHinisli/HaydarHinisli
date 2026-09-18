"""Fix-Sprint (docs/DECISIONS.md ADR-051): WebSocket Origin allowlist — pure
function tests. WS-level integration is in tests/test_live_suggestions_ws.py.
"""
from app.services.ws_origin import is_allowed_origin, parse_allowed_origins


def test_parse_allowed_origins_splits_and_trims():
    assert parse_allowed_origins('https://a.example, https://b.example ,,') == ['https://a.example', 'https://b.example']


def test_parse_allowed_origins_empty_or_none_returns_empty_list():
    assert parse_allowed_origins(None) == []
    assert parse_allowed_origins('') == []


def test_local_env_allows_anything_including_missing_origin():
    assert is_allowed_origin(None, env='local', allowed_origins=[]) is True
    assert is_allowed_origin('https://anything.example', env='local', allowed_origins=[]) is True


def test_production_env_rejects_missing_origin():
    assert is_allowed_origin(None, env='production', allowed_origins=['https://app.example']) is False


def test_production_env_rejects_origin_not_on_the_allowlist():
    assert is_allowed_origin('https://evil.example', env='production', allowed_origins=['https://app.example']) is False


def test_production_env_accepts_an_allowlisted_origin():
    assert is_allowed_origin('https://app.example', env='production', allowed_origins=['https://app.example']) is True


def test_staging_env_is_gated_the_same_as_production():
    assert is_allowed_origin('https://evil.example', env='staging', allowed_origins=['https://app.example']) is False
    assert is_allowed_origin('https://app.example', env='staging', allowed_origins=['https://app.example']) is True


def test_unset_allowlist_rejects_everything_outside_local():
    assert is_allowed_origin('https://app.example', env='production', allowed_origins=[]) is False
