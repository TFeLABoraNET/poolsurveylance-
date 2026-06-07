"""Datenbank-Zugriffe und Erst-Befüllung (Seed)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Chemical, ChecklistCheck, ChecklistRun, Measurement,
    PoolConfig, PumpLog, TabletDispenser,
)

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


def update_chemical_stock(db: Session, chem: Chemical, stock_g: float | None) -> None:
    chem.stock_g = stock_g
    chem.stock_updated_at = datetime.now(timezone.utc)
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


def list_measurements_asc(db: Session, limit: int = 90) -> list[Measurement]:
    stmt = select(Measurement).order_by(Measurement.measured_at.asc()).limit(limit)
    return list(db.scalars(stmt).all())


def delete_measurement(db: Session, m: Measurement) -> None:
    db.delete(m)
    db.commit()


# --- Tabletten-Dosierer --------------------------------------------------

def get_dispenser(db: Session) -> TabletDispenser:
    disp = db.scalars(select(TabletDispenser).limit(1)).first()
    if disp is None:
        disp = TabletDispenser()
        db.add(disp)
        db.commit()
        db.refresh(disp)
    return disp


def update_dispenser(db: Session, disp: TabletDispenser, data: dict) -> TabletDispenser:
    for key, value in data.items():
        setattr(disp, key, value)
    db.commit()
    db.refresh(disp)
    return disp


def set_dispenser_count(db: Session, disp: TabletDispenser, count: int, is_refill: bool = False) -> None:
    disp.current_count = max(0, count)
    if is_refill:
        disp.last_refill_at = datetime.now(timezone.utc)
    db.commit()


# --- Pumpenlaufzeit-Protokoll --------------------------------------------

def log_pump(db: Session, log_date: date, runtime_hours: float,
             backwashed: bool = False, note: str | None = None) -> PumpLog:
    existing = db.scalars(select(PumpLog).where(PumpLog.log_date == log_date)).first()
    if existing:
        existing.runtime_hours = runtime_hours
        existing.backwashed = backwashed
        existing.note = note
        db.commit()
        db.refresh(existing)
        return existing
    entry = PumpLog(log_date=log_date, runtime_hours=runtime_hours,
                    backwashed=backwashed, note=note)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_pump_logs(db: Session, limit: int = 30) -> list[PumpLog]:
    stmt = select(PumpLog).order_by(PumpLog.log_date.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_pump_stats(db: Session, backwash_interval: float = 50.0) -> dict:
    """Berechnet Statistiken: Gesamtstunden, Zeit seit letztem Rückspülen."""
    logs = list(db.scalars(select(PumpLog).order_by(PumpLog.log_date.desc()).limit(365)).all())
    if not logs:
        return {"total_hours": 0.0, "hours_since_backwash": 0.0,
                "backwash_due": False, "last_backwash": None,
                "week_hours": 0.0, "month_hours": 0.0}

    from datetime import timedelta
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    total = sum(l.runtime_hours for l in logs)
    week_h = sum(l.runtime_hours for l in logs if l.log_date >= week_ago)
    month_h = sum(l.runtime_hours for l in logs if l.log_date >= month_ago)

    last_backwash_log = next((l for l in logs if l.backwashed), None)
    if last_backwash_log:
        hours_since = sum(
            l.runtime_hours for l in logs
            if l.log_date > last_backwash_log.log_date
        )
    else:
        hours_since = total

    return {
        "total_hours": round(total, 1),
        "hours_since_backwash": round(hours_since, 1),
        "backwash_due": hours_since >= backwash_interval,
        "last_backwash": last_backwash_log.log_date if last_backwash_log else None,
        "week_hours": round(week_h, 1),
        "month_hours": round(month_h, 1),
    }


# --- Checklisten ---------------------------------------------------------

def start_checklist(db: Session, checklist_type: str) -> ChecklistRun:
    run = ChecklistRun(checklist_type=checklist_type)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_checklist_run(db: Session, run_id: int) -> ChecklistRun | None:
    return db.get(ChecklistRun, run_id)


def list_active_checklists(db: Session) -> list[ChecklistRun]:
    stmt = select(ChecklistRun).where(
        ChecklistRun.completed_at.is_(None)
    ).order_by(ChecklistRun.started_at.desc())
    return list(db.scalars(stmt).all())


def list_checklist_history(db: Session, limit: int = 10) -> list[ChecklistRun]:
    stmt = select(ChecklistRun).where(
        ChecklistRun.completed_at.isnot(None)
    ).order_by(ChecklistRun.completed_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def get_checked_tasks(db: Session, run_id: int) -> set[str]:
    checks = db.scalars(
        select(ChecklistCheck).where(ChecklistCheck.run_id == run_id)
    ).all()
    return {c.task_key for c in checks}


def toggle_task(db: Session, run_id: int, task_key: str) -> None:
    existing = db.scalars(
        select(ChecklistCheck).where(
            ChecklistCheck.run_id == run_id,
            ChecklistCheck.task_key == task_key,
        )
    ).first()
    if existing:
        db.delete(existing)
    else:
        db.add(ChecklistCheck(run_id=run_id, task_key=task_key))
    db.commit()


def close_checklist(db: Session, run: ChecklistRun) -> None:
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


def delete_checklist(db: Session, run: ChecklistRun) -> None:
    db.scalars(select(ChecklistCheck).where(ChecklistCheck.run_id == run.id))
    db.execute(
        ChecklistCheck.__table__.delete().where(ChecklistCheck.run_id == run.id)
    )
    db.delete(run)
    db.commit()


# --- Seed -----------------------------------------------------------------

def seed_defaults(db: Session) -> None:
    """Legt Pool-Konfiguration, Standard-Chemikalien und Dosierer an, falls leer."""
    get_config(db)
    existing = db.scalar(select(Chemical).limit(1))
    if existing is None:
        for data in DEFAULT_CHEMICALS:
            db.add(Chemical(**data))
        db.commit()
    get_dispenser(db)
