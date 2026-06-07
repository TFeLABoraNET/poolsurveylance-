"""Datenbank-Setup (SQLite via SQLAlchemy)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# check_same_thread=False ist für SQLite + FastAPI nötig.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Basisklasse für alle ORM-Modelle."""


def get_db() -> Iterator[Session]:
    """FastAPI-Dependency: liefert eine DB-Session und schließt sie sauber."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
