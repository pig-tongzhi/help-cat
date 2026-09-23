from sqlalchemy import create_engine, event
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
    if database_url.startswith("sqlite"):
        # SQLite defaults (journal_mode=delete, no busy_timeout) make readers and
        # writers block each other, so a second worker hits "database is locked".
        # WAL + a bounded busy timeout let concurrent requests wait instead of fail.
        @event.listens_for(engine, "connect")
        def _apply_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")  # no-op on :memory:
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_schema(engine):
    """Make a database usable without running Alembic.

    Alembic owns the schema of a deployed database.  This bootstrap still
    creates any missing table straight from the models and replays the
    historical column repairs, so a legacy pilot database boots and the test
    suite gets one-call setup.  The repairs live in ``schema_upgrades`` and are
    shared with migration ``011_bootstrap_parity``, so the two paths cannot
    drift apart the way the old inline ALTER list did.
    """
    from . import models  # noqa: F401 - register the tables before create_all
    from .schema_upgrades import apply_legacy_upgrades

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        apply_legacy_upgrades(connection)

