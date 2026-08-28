"""Alembic environment. URL comes from ForiFlow config, not this file."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from config import database_url
from models.database import Base

config = context.config
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    # disable_existing_loggers=False avoids a deadlock when upgrade runs
    # in-process from FastAPI startup (uvicorn already holds the logging lock).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# init_db() and tests inject sqlalchemy.url on the Config object. Keep that
# value; only fill in from process env when alembic.ini still has the stub.
_PLACEHOLDER_URL = "driver://user:pass@localhost/dbname"
_configured = (config.get_main_option("sqlalchemy.url") or "").strip()
if not _configured or _configured == _PLACEHOLDER_URL:
    config.set_main_option("sqlalchemy.url", database_url().replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations against a URL without a live connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live Engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
