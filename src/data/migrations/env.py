"""Alembic environment configuration."""

from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy import engine_from_config

from alembic import context

from src.data.models import Base as AgentBase
from src.data.database import DATABASE_URL

# Import dashboard models for migration support
try:
    from dashboard.backend.app.database import Base as DashboardBase
    # Combine metadata from both bases using merge
    target_metadata = AgentBase.metadata
    DashboardBase.metadata.create_all = lambda *args, **kwargs: None  # Prevent auto-create
    # Merge dashboard metadata into agent metadata
    for table in DashboardBase.metadata.tables.values():
        if table.name not in target_metadata.tables:
            table.tometadata(target_metadata)
except ImportError:
    # Dashboard not installed yet, use only agent base
    target_metadata = AgentBase.metadata

# this is the Alembic Config object
config = context.config

# Set the SQLAlchemy URL programmatically
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
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
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
