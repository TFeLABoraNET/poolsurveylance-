"""Tests für ORP-Ingest und die Säure-Dosier-Protokollierung."""

from app import crud
from app.database import Base
from app.models import PoolConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# --- ORP -----------------------------------------------------------------

def test_ingest_accepts_orp():
    db = _session()
    m = crud.ingest_measurement(db, {"orp": "705", "source": "esp32"})
    assert m is not None
    assert m.orp == 705.0


def test_orp_alone_is_a_valid_measurement():
    db = _session()
    assert crud.ingest_measurement(db, {"orp": 700}) is not None


# --- Dosier-Stöße --------------------------------------------------------

def test_ingest_dose_event_records_ml_and_fields():
    db = _session()
    ev = crud.ingest_dose_event(db, {
        "ml": 100, "ph_before": 7.6, "ph_target": 7.2,
        "pump_seconds": 100, "trigger": "auto",
    })
    assert ev is not None
    assert ev.ml == 100.0
    assert ev.ph_before == 7.6
    assert ev.trigger == "auto"
    assert ev.source == "esp32"


def test_dose_event_requires_ml():
    db = _session()
    assert crud.ingest_dose_event(db, {"ph_before": 7.5}) is None
    assert crud.ingest_dose_event(db, {"ml": "kaputt"}) is None
    assert crud.ingest_dose_event(db, {"ml": -5}) is None


def test_dose_total_and_budget():
    db = _session()
    cfg = PoolConfig(id=1, dose_max_ml_day=500.0)
    db.add(cfg)
    db.commit()
    crud.ingest_dose_event(db, {"ml": 100})
    crud.ingest_dose_event(db, {"ml": 150})
    assert crud.dose_total_ml_today(db) == 250.0
    assert crud.dose_budget_remaining_ml(db, cfg) == 250.0


def test_dose_event_deducts_acid_stock():
    db = _session()
    acid = crud.create_chemical(db, {
        "name": "Säure 15%", "purpose": "ph_minus", "unit": "ml",
        "ref_dose_amount": 100, "ref_volume_m3": 10, "ref_effect_delta": 0.1,
        "stock_g": 1000.0, "is_active": 1,
    })
    crud.ingest_dose_event(db, {"ml": 120})
    db.refresh(acid)
    assert acid.stock_g == 880.0
