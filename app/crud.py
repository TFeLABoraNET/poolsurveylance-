"""Datenbank-Zugriffe und Erst-Befüllung (Seed)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Chemical, Measurement, PoolConfig

# Standard-Chemikalien (typische Produkte für private Pools).
# Werte sind Startwerte – bitte an die Angaben auf deiner Verpackung anpassen!
DEFAULT_CHEMICALS = [
    dict(name="pH-Minus Granulat", purpose="ph_minus", unit="g",
         ref_dose_amount=100, ref_volume_m3=10, ref_effect_delta=0.1,
         notes="Typisch: 100 g pro 10 m³ senken den pH-Wert um ca. 0,1."),
    dict(name="pH-Plus Granulat", purpose="ph_plus", unit="g",
         ref_dose_amount=100, ref_volume_m3=10, ref_effect_delta=0.1,
         notes="Typisch: 100 g pro 10 m³ heben den pH-Wert um ca. 0,1."),
    dict(name="Chlorgranulat (schnell)", purpose="chlorine_free", unit="g",
         ref_dose_amount=17, ref_volume_m3=10, ref_effect_delta=1.0,
         active_ingredient_pct=56,
         notes="Typisch: ~17 g pro 10 m³ heben das freie Chlor um ca. 1 mg/l."),
    dict(name="Chlor-Schock Granulat", purpose="chlorine_shock", unit="g",
         ref_dose_amount=20, ref_volume_m3=10, ref_effect_delta=1.0,
         active_ingredient_pct=56,
         notes="Für Stoßchlorung. Menge an Verpackung anpassen."),
    dict(name="Alkalinität-Plus (Natron)", purpose="alkalinity_plus", unit="g",
         ref_dose_amount=170, ref_volume_m3=10, ref_effect_delta=10.0,
         notes="Typisch: ~170 g pro 10 m³ heben die Alkalinität (TA) um ca. 10 mg/l."),
    dict(name="Stabilisator (Cyanursäure)", purpose="stabilizer", unit="g",
         ref_dose_amount=100, ref_volume_m3=10, ref_effect_delta=10.0,
         notes="Typisch: ~100 g pro 10 m³ heben die Cyanursäure um ca. 10 mg/l."),
]


# --- Pool-Konfiguration ---------------------------------------------------

def get_config(db: Session) -> PoolConfig:
    cfg = db.get(PoolConfig, 1)
    if cfg is None:
        cfg = PoolConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


# --- Chemikalien ----------------------------------------------------------

def list_chemicals(db: Session, only_active: bool = False) -> list[Chemical]:
    stmt = select(Chemical).order_by(Chemical.purpose, Chemical.name)
    if only_active:
        stmt = stmt.where(Chemical.is_active == 1)
    return list(db.scalars(stmt).all())


def get_chemical(db: Session, chem_id: int) -> Chemical | None:
    return db.get(Chemical, chem_id)


def create_chemical(db: Session, data: dict) -> Chemical:
    chem = Chemical(**data)
    db.add(chem)
    db.commit()
    db.refresh(chem)
    return chem


def update_chemical(db: Session, chem: Chemical, data: dict) -> Chemical:
    for key, value in data.items():
        setattr(chem, key, value)
    db.commit()
    db.refresh(chem)
    return chem


def delete_chemical(db: Session, chem: Chemical) -> None:
    db.delete(chem)
    db.commit()


# --- Messwerte ------------------------------------------------------------

def create_measurement(db: Session, data: dict) -> Measurement:
    m = Measurement(**data)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def latest_measurement(db: Session) -> Measurement | None:
    stmt = select(Measurement).order_by(Measurement.measured_at.desc()).limit(1)
    return db.scalars(stmt).first()


def list_measurements(db: Session, limit: int = 50) -> list[Measurement]:
    stmt = select(Measurement).order_by(Measurement.measured_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def delete_measurement(db: Session, m: Measurement) -> None:
    db.delete(m)
    db.commit()


# --- Seed -----------------------------------------------------------------

def seed_defaults(db: Session) -> None:
    """Legt Pool-Konfiguration und Standard-Chemikalien an, falls leer."""
    get_config(db)  # stellt sicher, dass eine Konfig existiert
    existing = db.scalar(select(Chemical).limit(1))
    if existing is None:
        for data in DEFAULT_CHEMICALS:
            db.add(Chemical(**data))
        db.commit()
