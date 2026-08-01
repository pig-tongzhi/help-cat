from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_session_factory(database_url):
    kwargs = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_schema(engine):
    """Small forward-only bootstrap for the existing pilot SQLite database.

    Production changes must be promoted through Alembic; this guard keeps the
    already deployed pilot database readable while the migration is rolled out.
    """
    from . import models  # noqa: F401 - ensure model tables are registered for CLI/migration callers
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    statements = []
    user_columns = {item["name"] for item in inspector.get_columns("users")}
    session_columns = {item["name"] for item in inspector.get_columns("sessions")}
    cat_columns = {item["name"] for item in inspector.get_columns("cats")}
    if "username" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN username VARCHAR(80)")
    if "password_hash" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
    if "revoked_at" not in session_columns:
        statements.append("ALTER TABLE sessions ADD COLUMN revoked_at DATETIME")
    if "latitude" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN latitude FLOAT")
    if "longitude" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN longitude FLOAT")
    if "photo_asset_id" not in cat_columns:
        statements.append("ALTER TABLE cats ADD COLUMN photo_asset_id VARCHAR(32)")
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
