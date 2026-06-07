"""ORM-Modelle: Pool-Konfiguration, Chemikalien, Messwerte."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PoolConfig(Base):
    """Einstellungen des Pools. Es gibt genau einen Datensatz (id=1)."""

    __tablename__ = "pool_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(120), default="Mein Pool")

    # Beckendaten
    volume_m3: Mapped[float] = mapped_column(Float, default=10.0)
    pump_flow_m3h: Mapped[float] = mapped_column(Float, default=8.0)

    # Zielwerte / akzeptierte Bereiche
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

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Chemical(Base):
    """Eine Chemikalie inkl. Referenz-Dosierung (von der Verpackung).

    Die Dosierung wird so erfasst, wie sie auf dem Produkt steht, z. B.::

        "100 g pro 10 m³ senken den pH-Wert um 0,1"

    Daraus rechnet die App die nötige Menge für dein Beckenvolumen aus.
    """

    __tablename__ = "chemicals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))

    # Wofür wird die Chemikalie eingesetzt? (siehe chemistry.PURPOSES)
    purpose: Mapped[str] = mapped_column(String(40))

    # Einheit der Dosiermenge: "g" (Pulver/Granulat) oder "ml" (flüssig)
    unit: Mapped[str] = mapped_column(String(8), default="g")

    # Referenz-Dosierung laut Verpackung
    ref_dose_amount: Mapped[float] = mapped_column(Float, default=100.0)  # z. B. 100 (g)
    ref_volume_m3: Mapped[float] = mapped_column(Float, default=10.0)     # je 10 m³
    ref_effect_delta: Mapped[float] = mapped_column(Float, default=0.1)   # ändert Wert um 0,1

    # Optionale Zusatzinfo
    active_ingredient_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Measurement(Base):
    """Ein manuell (später per Sonde) erfasster Messwert-Satz."""

    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Quelle: "manual" jetzt, später z. B. "esp32"
    source: Mapped[str] = mapped_column(String(20), default="manual")

    ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_cl: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cl: Mapped[float | None] = mapped_column(Float, nullable=True)
    ta: Mapped[float | None] = mapped_column(Float, nullable=True)
    cya: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
