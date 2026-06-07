"""Datenbank-Setup (SQLite via SQLAlchemy)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

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


def migrate_schema(eng) -> None:
    """Fügt neue Spalten zu bestehenden Tabellen hinzu (idempotent)."""
    new_cols = [
        ("pool_config", "fc_min_dynamic", "INTEGER DEFAULT 0"),
        ("pool_config", "cya_warning_level", "REAL DEFAULT 70.0"),
        ("pool_config", "cya_dilution_target", "REAL DEFAULT 30.0"),
        ("pool_config", "backwash_interval_hours", "REAL DEFAULT 50.0"),
        ("chemicals", "stock_g", "REAL"),
        ("chemicals", "stock_updated_at", "TEXT"),
    ]
    with eng.connect() as conn:
        for table, col, typedef in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                pass
