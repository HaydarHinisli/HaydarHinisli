"""Sprint 3A: EU provider preparation (docs/DECISIONS.md ADR-049) — the Twilio
REST client factory must never silently fall back to the Twilio SDK's own us1
region/edge default, and region/edge must be configurable rather than hardcoded.
"""
import pytest

from app.integrations import twilio_rest


def test_status_reports_region_and_edge(monkeypatch):
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', 'ACxxx')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'tok')
    monkeypatch.setenv('TWILIO_REGION', 'ie1')
    monkeypatch.setenv('TWILIO_EDGE', 'dublin')
    try:
        status = twilio_rest.status()
        assert status['connected'] is True
        assert status['region'] == 'ie1'
        assert status['edge'] == 'dublin'
    finally:
        config_module.get_settings.cache_clear()


def test_client_construction_passes_region_and_edge_explicitly(monkeypatch):
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', 'ACxxx')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'tok')
    monkeypatch.setenv('TWILIO_REGION', 'ie1')
    monkeypatch.setenv('TWILIO_EDGE', 'dublin')
    try:
        client = twilio_rest.get_twilio_rest_client()
        # The Twilio SDK's Client stores the constructor args it was given —
        # asserting on these proves we never omitted region/edge and let the SDK
        # inherit its own us1 default.
        assert client.region == 'ie1'
        assert client.edge == 'dublin'
    finally:
        config_module.get_settings.cache_clear()


def test_client_construction_refuses_when_region_not_configured(monkeypatch):
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', 'ACxxx')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', 'tok')
    monkeypatch.setenv('TWILIO_REGION', '')
    monkeypatch.setenv('TWILIO_EDGE', 'dublin')
    try:
        with pytest.raises(ValueError):
            twilio_rest.get_twilio_rest_client()
    finally:
        config_module.get_settings.cache_clear()


def test_client_construction_refuses_without_credentials(monkeypatch):
    import app.config as config_module
    config_module.get_settings.cache_clear()
    monkeypatch.setenv('TWILIO_ACCOUNT_SID', '')
    monkeypatch.setenv('TWILIO_AUTH_TOKEN', '')
    try:
        with pytest.raises(ValueError):
            twilio_rest.get_twilio_rest_client()
    finally:
        config_module.get_settings.cache_clear()
