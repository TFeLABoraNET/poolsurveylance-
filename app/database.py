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
        ("pool_config", "pump_timer_hours", "REAL DEFAULT 8.0"),
        ("pool_config", "pump_auto_track", "INTEGER DEFAULT 0"),
        ("chemicals", "stock_g", "REAL"),
        ("chemicals", "min_stock_g", "REAL"),
        ("chemicals", "stock_updated_at", "TEXT"),
        ("pump_logs", "source", "TEXT DEFAULT 'manual'"),
        ("tablet_dispensers", "tab_lifetime_days", "REAL DEFAULT 10.0"),
        ("measurements", "orp", "REAL"),
        ("pool_config", "orp_min", "REAL DEFAULT 650.0"),
        ("pool_config", "orp_target", "REAL DEFAULT 700.0"),
        ("pool_config", "orp_max", "REAL DEFAULT 800.0"),
        ("pool_config", "dosing_enabled", "INTEGER DEFAULT 0"),
        ("pool_config", "acid_concentration_pct", "REAL DEFAULT 15.0"),
        ("pool_config", "dose_ml_per_shot", "REAL DEFAULT 100.0"),
        ("pool_config", "dose_max_ml_day", "REAL DEFAULT 1000.0"),
        ("pool_config", "dose_pump_ml_per_min", "REAL DEFAULT 60.0"),
        ("pool_config", "dose_wait_minutes", "REAL DEFAULT 15.0"),
        ("pool_config", "ph_dose_deadband", "REAL DEFAULT 0.1"),
        ("pool_config", "ph_dose_floor", "REAL DEFAULT 6.8"),
    ]
    with eng.connect() as conn:
        for table, col, typedef in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                pass
