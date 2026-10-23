"""SQLite engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base


class Database:
    """Owns the SQLAlchemy engine and hands out short-lived sessions."""

    def __init__(self, db_path: Path | None) -> None:
        url = f"sqlite:///{db_path}" if db_path is not None else "sqlite://"
        self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", _enable_wal)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session that commits on success and rolls back on error."""
        session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _enable_wal(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
