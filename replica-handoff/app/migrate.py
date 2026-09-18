"""Runs Alembic migrations programmatically at app startup, replacing the old
Base.metadata.create_all() call. This means:
  - schema changes are versioned (migrations/versions/*.py), not implicit;
  - a stale local SQLite file no longer needs to be deleted between pulls —
    `alembic upgrade head` brings it forward instead (see docs/DECISIONS.md ADR-017);
  - the same code path works unchanged against Postgres in staging/production.

`alembic upgrade head` is idempotent, so calling this on every process start is safe
for a single-instance pilot. A multi-instance production deploy should instead run
migrations as an explicit, separate deploy step (out of scope for Sprint 1).
"""
from __future__ import annotations
from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / 'alembic.ini'


def run_migrations() -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option('script_location', str(PROJECT_ROOT / 'migrations'))
    cfg.set_main_option('sqlalchemy.url', get_settings().replica_database_url)
    command.upgrade(cfg, 'head')
