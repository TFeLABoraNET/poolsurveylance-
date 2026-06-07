"""ORM-Modelle: Pool-Konfiguration, Chemikalien, Messwerte, Pumpenlog, Tabletten, Checklisten."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PoolConfig(Base):
    """Einstellungen des Pools. Es gibt genau einen Datensatz (id=1)."""

    __tablename__ = "pool_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(120), default="Mein Pool")

    volume_m3: Mapped[float] = mapped_column(Float, default=10.0)
    pump_flow_m3h: Mapped[float] = mapped_column(Float, default=8.0)

    ph_min: Mapped[float] = mapped_column(Float, default=7.0)
    ph_target: Mapped[float] = mapped_column(Float, default=7.2)
    ph_max: Mapped[float] = mapped_column(Float, default=7.4)

    free_cl_min: Mapped[float] = mapped_column(Float, default=1.0)
    free_cl_target: Mapped[float] = mapped_column(Float, default=1.5)
    free_cl_max: Mapped[float] = mapped_column(Float, default=3.0)

    ta_min: Mapped[float] = mapped_column(Float, default=80.0)
    ta_target: Mapped[float] = mapped_column(Float, default=100.0)
    ta_max: Mapped[float] = mapped_column(Float, default=120.0)

    cya_min: Mapped[float] = mapped_column(Float, default=30.0)
    cya_target: Mapped[float] = mapped_column(Float, default=40.0)
    cya_max: Mapped[float] = mapped_column(Float, default=50.0)

    # Erweiterungen
    fc_min_dynamic: Mapped[bool] = mapped_column(Integer, default=0)
    cya_warning_level: Mapped[float] = mapped_column(Float, default=70.0)
    cya_dilution_target: Mapped[float] = mapped_column(Float, default=30.0)
    backwash_interval_hours: Mapped[float] = mapped_column(Float, default=50.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Chemical(Base):
    """Eine Chemikalie inkl. Referenz-Dosierung (von der Verpackung)."""

    __tablename__ = "chemicals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(40))
    unit: Mapped[str] = mapped_column(String(8), default="g")

    ref_dose_amount: Mapped[float] = mapped_column(Float, default=100.0)
    ref_volume_m3: Mapped[float] = mapped_column(Float, default=10.0)
    ref_effect_delta: Mapped[float] = mapped_column(Float, default=0.1)

    active_ingredient_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    stock_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    is_active: Mapped[bool] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Measurement(Base):
    """Ein manuell (später per Sonde) erfasster Messwert-Satz."""

    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    source: Mapped[str] = mapped_column(String(20), default="manual")

    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_cl: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cl: Mapped[float | None] = mapped_column(Float, nullable=True)
    ta: Mapped[float | None] = mapped_column(Float, nullable=True)
    cya: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TabletDispenser(Base):
    """Tabletten-Dosierer – verfolgt den aktuellen Tablettenvorrat."""

    __tablename__ = "tablet_dispensers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), default="Dosierer")
    tablet_weight_g: Mapped[float] = mapped_column(Float, default=200.0)
    current_count: Mapped[int] = mapped_column(Integer, default=0)
    last_refill_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    daily_consumption_tabs: Mapped[float] = mapped_column(Float, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PumpLog(Base):
    """Tägliches Pumpenlaufzeit-Protokoll."""

    __tablename__ = "pump_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_date: Mapped[date] = mapped_column(Date, unique=True)
    runtime_hours: Mapped[float] = mapped_column(Float)
    backwashed: Mapped[bool] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ChecklistRun(Base):
    """Eine gestartete Checklisten-Instanz."""

    __tablename__ = "checklist_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checklist_type: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChecklistCheck(Base):
    """Abgehakter Aufgaben-Eintrag einer Checklisten-Instanz."""

    __tablename__ = "checklist_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("checklist_runs.id", ondelete="CASCADE"))
    task_key: Mapped[str] = mapped_column(String(80))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
