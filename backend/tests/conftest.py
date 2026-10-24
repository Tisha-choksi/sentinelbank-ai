import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 - registers all tables on Base.metadata
from db import Base, get_db


@pytest.fixture()
def db_session():
    """A fresh in-memory SQLite database per test.

    This exercises the same SQLAlchemy models, constraints, and
    relationships as production without touching the real Postgres
    container, so the test suite can run offline and never mutates real
    data.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def api_client(tmp_path):
    """A FastAPI TestClient wired to its own SQLite database (via a
    `get_db` override), for exercising real HTTP routes end-to-end -- auth,
    status codes, concurrency -- without touching the real Postgres
    container.

    Backed by a temp file rather than `:memory:`/StaticPool: an in-memory
    DB under StaticPool shares one literal connection across every thread,
    so concurrent requests interleave the *same* connection's transaction
    state and silently corrupt each other's commits -- exactly the kind of
    false negative a concurrency test must not produce. A temp file gives
    each session its own real connection with SQLite's normal file-level
    locking, which is what the concurrent-review test actually needs to be
    a valid test.
    """
    from fastapi.testclient import TestClient

    from main import app

    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app), session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
