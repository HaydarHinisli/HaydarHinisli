import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app import models  # noqa: E402,F401  (registers all mapped classes on Base.metadata)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Always resolve the DB URL from the app's own settings (REPLICA_DATABASE_URL /
# .env) rather than a hardcoded alembic.ini value, so `alembic upgrade head`
# targets whatever the app itself is configured to use (SQLite locally,
# Postgres via docker-compose/production) without editing two files.
config.set_main_option("sqlalchemy.url", get_settings().replica_database_url)

# Interpret the config file for Python logging.
# disable_existing_loggers=False is required here: this app runs migrations
# programmatically from app/migrate.py on every process start (see startup() in
# app/main.py), and fileConfig()'s default of True would silently disable the
# already-configured 'replica.access' structured-logging logger (and any other
# app logger that happens to exist yet) the moment migrations run.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
