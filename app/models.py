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

    # Redox / ORP (mV) – Maß für die Desinfektionskraft (korreliert mit Chlor).
    orp_min: Mapped[float] = mapped_column(Float, default=650.0)
    orp_target: Mapped[float] = mapped_column(Float, default=700.0)
    orp_max: Mapped[float] = mapped_column(Float, default=800.0)

    # --- Automatische pH-Minus-Dosierung (Schwefelsäure, Quetschschlauchpumpe) ---
    # Die eigentliche Regelung läuft autonom auf dem ESP32 (ESPHome). Diese
    # Werte sind die Sollvorgaben/Schutzgrenzen, die die App führt, anzeigt und
    # (optional per MQTT) an den ESP32 spiegelt. Sicherheits-kritisch: konservativ.
    dosing_enabled: Mapped[bool] = mapped_column(Integer, default=0)
    acid_concentration_pct: Mapped[float] = mapped_column(Float, default=15.0)
    # Säurelösung in g/l? Nein – wir rechnen in ml Lösung (einfach + robust).
    dose_ml_per_shot: Mapped[float] = mapped_column(Float, default=100.0)
    dose_max_ml_day: Mapped[float] = mapped_column(Float, default=1000.0)
    dose_pump_ml_per_min: Mapped[float] = mapped_column(Float, default=60.0)
    dose_wait_minutes: Mapped[float] = mapped_column(Float, default=15.0)
    # Erst dosieren, wenn pH über Ziel + Totband liegt (verhindert Pendeln).
    ph_dose_deadband: Mapped[float] = mapped_column(Float, default=0.1)
    # Harte Untergrenze: unter diesem pH wird NIE dosiert (Sicherheitsboden).
    ph_dose_floor: Mapped[float] = mapped_column(Float, default=6.8)

    # Erweiterungen
    fc_min_dynamic: Mapped[bool] = mapped_column(Integer, default=0)
    cya_warning_level: Mapped[float] = mapped_column(Float, default=70.0)
    cya_dilution_target: Mapped[float] = mapped_column(Float, default=30.0)
    backwash_interval_hours: Mapped[float] = mapped_column(Float, default=50.0)

    # Pumpen-Timer (automatisches tägliches Tracking)
    pump_timer_hours: Mapped[float] = mapped_column(Float, default=8.0)
    pump_auto_track: Mapped[bool] = mapped_column(Integer, default=0)

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
    min_stock_g: Mapped[float | None] = mapped_column(Float, nullable=True)
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
    orp: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DoseEvent(Base):
    """Protokoll einer automatischen Säure-Dosierung (pH-Minus).

    Wird vom ESP32-Dosiercontroller nach jedem Dosierstoß gemeldet (HTTP/MQTT).
    Dient der Nachverfolgung, der Tagesmengen-Begrenzung und als Sicherheits-
    Audit-Trail (wie viel Säure wurde wann auf welcher Grundlage zugegeben).
    """

    __tablename__ = "dose_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dosed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    source: Mapped[str] = mapped_column(String(20), default="esp32")

    # Welches Mittel (Vorrat ist meist "ph_minus"); hier fix für die Säurepumpe.
    purpose: Mapped[str] = mapped_column(String(20), default="ph_minus")
    ml: Mapped[float] = mapped_column(Float, default=0.0)
    pump_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    ph_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    ph_target: Mapped[float | None] = mapped_column(Float, nullable=True)

    # "auto" (Regler), "manual" (Hand-Auslösung), "fault" (abgebrochen)
    trigger: Mapped[str] = mapped_column(String(12), default="auto")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TabletDispenser(Base):
    """Schwimm-/Skimmer-Dosierer – verfolgt den AKTUELL eingelegten Chlor-Tab.

    Bewusst getrennt vom Lager (das Granulat/Flüssigkeiten in g/ml führt):
    hier geht es nur um die Tablette, die GERADE im Pool liegt und sich
    langsam auflöst – inkl. Schätzung, wann sie aufgebraucht ist.
    """

    __tablename__ = "tablet_dispensers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), default="Schwimmdosierer")
    tablet_weight_g: Mapped[float] = mapped_column(Float, default=200.0)
    # Wie viele Tabs liegen gleichzeitig im Dosierer (im Regelfall 1).
    current_count: Mapped[int] = mapped_column(Integer, default=1)
    # Wann wurde der aktuelle Tab eingelegt?
    last_refill_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Wie lange hält ein Tab ungefähr (Tage)? Grundlage der Rest-Schätzung.
    tab_lifetime_days: Mapped[float] = mapped_column(Float, default=10.0)
    # (veraltet, bleibt aus Kompatibilitätsgründen erhalten)
    daily_consumption_tabs: Mapped[float] = mapped_column(Float, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PumpLog(Base):
    """Tägliches Pumpenlaufzeit-Protokoll."""

    __tablename__ = "pump_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_date: Mapped[date] = mapped_column(Date, unique=True)
    runtime_hours: Mapped[float] = mapped_column(Float)
    backwashed: Mapped[bool] = mapped_column(Integer, default=0)
    # Quelle: "manual" (Hand-Eintrag) oder "auto" (Timer-Tracking)
    source: Mapped[str] = mapped_column(String(10), default="manual")
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
