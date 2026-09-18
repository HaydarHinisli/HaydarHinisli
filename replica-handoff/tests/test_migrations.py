"""Proves `alembic upgrade head` brings a completely empty, fresh database (no prior
replica.db, no Base.metadata.create_all()) all the way to the current schema — the
Sprint 1 requirement that a stale local SQLite file no longer needs to be deleted
between pulls (see docs/DECISIONS.md ADR-017), tested against a real empty file, not
mocked.
"""
import os
import tempfile

from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.migrate import PROJECT_ROOT

EXPECTED_TABLES = {
    'companies', 'sellers', 'calls', 'turns', 'suggestions', 'meetings', 'deals',
    'experiments', 'experiment_assignments', 'audit_events', 'consent_events',
    'tenant_feature_flags', 'compliance_review_signoffs', 'users',
}


def test_migration_from_empty_database_creates_full_schema(monkeypatch):
    fd, path = tempfile.mkstemp(prefix='replica_migration_test_', suffix='.db')
    os.close(fd)
    os.remove(path)  # must not exist yet — this is the "empty production database" case
    try:
        # migrations/env.py always resolves sqlalchemy.url from get_settings()
        # (REPLICA_DATABASE_URL), by design, so the app's own migrations always run
        # against whatever the app is configured for — not a URL merely set on the
        # Config object. Point it at our scratch file the same way the real app would.
        monkeypatch.setenv('REPLICA_DATABASE_URL', f'sqlite:///{path}')
        get_settings.cache_clear()

        cfg = Config(str(PROJECT_ROOT / 'alembic.ini'))
        cfg.set_main_option('script_location', str(PROJECT_ROOT / 'migrations'))
        command.upgrade(cfg, 'head')

        engine = create_engine(f'sqlite:///{path}')
        tables = set(inspect(engine).get_table_names())
        engine.dispose()
        missing = EXPECTED_TABLES - tables
        assert not missing, f'migration did not create: {missing}'

        # Idempotency: running upgrade head again against an already-current DB must
        # be a no-op, not an error (this is what happens on every app restart).
        command.upgrade(cfg, 'head')
    finally:
        get_settings.cache_clear()  # restore for the rest of the test session
        if os.path.exists(path):
            os.remove(path)


def test_migration_history_has_no_gaps_or_branches():
    cfg = Config(str(PROJECT_ROOT / 'alembic.ini'))
    cfg.set_main_option('script_location', str(PROJECT_ROOT / 'migrations'))
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f'expected exactly one migration head, found {heads} (unmerged branches?)'
