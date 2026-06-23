"""Tests für den Sensor-Eingang (ingest_measurement)."""

from app import crud
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _session():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_ingest_creates_measurement_with_default_source():
    db = _session()
    m = crud.ingest_measurement(db, {"ph": 7.2})
    assert m is not None
    assert m.ph == 7.2
    assert m.source == "esp32"


def test_ingest_accepts_string_numbers_and_multiple_fields():
    db = _session()
    m = crud.ingest_measurement(db, {"ph": "7,1".replace(",", "."), "temperature": "26.5"})
    assert m.ph == 7.1
    assert m.temperature == 26.5


def test_ingest_custom_source_and_note():
    db = _session()
    m = crud.ingest_measurement(db, {"free_cl": 1.4, "source": "labor", "note": "Handmessung"})
    assert m.source == "labor"
    assert m.note == "Handmessung"


def test_ingest_without_values_returns_none():
    db = _session()
    assert crud.ingest_measurement(db, {"source": "esp32"}) is None
    assert crud.ingest_measurement(db, {"ph": "kaputt"}) is None


def test_ingest_ignores_unknown_fields():
    db = _session()
    m = crud.ingest_measurement(db, {"ph": 7.0, "hacker": "drop table"})
    assert m is not None
    assert not hasattr(m, "hacker")
