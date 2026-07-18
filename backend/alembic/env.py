from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.models.base import Base, UTCDateTime

# import every model module so Base.metadata is fully populated for autogenerate
from app.models import agent_run, brief, channel_ai_history, channel_connection, connection, finding, invite, otp_code, signal, team, user, workspace  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Alembic's default renderer for a brand-new column referencing a
    custom TypeDecorator (like UTCDateTime) emits a bare, unimported class
    reference (`app.models.base.UTCDateTime()`), which raises NameError when
    the migration runs. Render it as its portable, underlying type instead -
    UTCDateTime only changes Python-side (de)serialization, not the actual
    DDL, so `DateTime(timezone=True)` is a faithful schema representation.
    """
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_item=render_item)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
