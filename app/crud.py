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


def update_chemical_stock(db: Session, chem: Chemical, stock_g: float | None,
                          min_stock_g: float | None = ...) -> None:
    chem.stock_g = stock_g
    if min_stock_g is not ...:
        chem.min_stock_g = min_stock_g
    chem.stock_updated_at = datetime.now(timezone.utc)
    db.commit()


def adjust_chemical_stock(db: Session, chem: Chemical, delta: float) -> None:
    """Verändert den Lagerbestand um ``delta`` (negativ = Verbrauch)."""
    current = chem.stock_g or 0.0
    chem.stock_g = max(0.0, current + delta)
    chem.stock_updated_at = datetime.now(timezone.utc)
    db.commit()


def low_stock_chemicals(db: Session) -> list[Chemical]:
    """Chemikalien, deren Bestand auf/unter der Warnschwelle liegt."""
    result = []
    for c in list_chemicals(db):
        if c.min_stock_g is not None and c.stock_g is not None and c.stock_g <= c.min_stock_g:
            result.append(c)
    return result


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


def insert_fresh_tab(db: Session, disp: TabletDispenser) -> None:
    """Neuen Tab einlegen: Einlege-Zeitpunkt auf jetzt setzen."""
    disp.last_refill_at = datetime.now(timezone.utc)
    if (disp.current_count or 0) < 1:
        disp.current_count = 1
    db.commit()


def remove_tab(db: Session, disp: TabletDispenser) -> None:
    """Dosierer als leer markieren (kein Tab eingelegt)."""
    disp.last_refill_at = None
    db.commit()


def tab_status(disp: TabletDispenser) -> dict:
    """Status des aktuell eingelegten Tabs: Resttage / aufgebraucht.

    Reine Berechnung (ohne DB-Zugriff), damit testbar.
    """
    lifetime = disp.tab_lifetime_days or 0.0
    if not disp.last_refill_at or lifetime <= 0:
        return {"inserted": False}

    inserted = disp.last_refill_at
    if inserted.tzinfo is None:
        inserted = inserted.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    days_used = (now - inserted).total_seconds() / 86400.0
    days_left = lifetime - days_used
    return {
        "inserted": True,
        "inserted_at": disp.last_refill_at,
        "days_used": int(days_used),
        "days_left": round(days_left, 1),
        "depleted": days_left <= 0,
        "lifetime_days": lifetime,
    }


# --- Pumpenlaufzeit-Protokoll --------------------------------------------

def log_pump(db: Session, log_date: date, runtime_hours: float,
             backwashed: bool = False, note: str | None = None,
             source: str = "manual") -> PumpLog:
    existing = db.scalars(select(PumpLog).where(PumpLog.log_date == log_date)).first()
    if existing:
        existing.runtime_hours = runtime_hours
        existing.backwashed = backwashed
        existing.note = note
        existing.source = source
        db.commit()
        db.refresh(existing)
        return existing
    entry = PumpLog(log_date=log_date, runtime_hours=runtime_hours,
                    backwashed=backwashed, note=note, source=source)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_pump_log(db: Session, log_id: int) -> PumpLog | None:
    return db.get(PumpLog, log_id)


def delete_pump_log(db: Session, entry: PumpLog) -> None:
    db.delete(entry)
    db.commit()


def backfill_auto_pump_logs(db: Session, cfg: PoolConfig) -> int:
    """Füllt fehlende Tage automatisch mit dem Timer-Wert (source='auto').

    Wird bei jedem Aufruf der Pumpen-Seite und beim Start ausgeführt.
    Manuelle Einträge (bereits vorhandene Tage) werden NIE überschrieben.
    Es wird höchstens 60 Tage rückwirkend aufgefüllt.
    """
    from datetime import timedelta

    if not cfg.pump_auto_track or (cfg.pump_timer_hours or 0) <= 0:
        return 0

    today = date.today()
    latest = db.scalars(select(PumpLog).order_by(PumpLog.log_date.desc()).limit(1)).first()
    if latest is None:
        start = today
    else:
        start = latest.log_date + timedelta(days=1)
    if (today - start).days > 60:
        start = today - timedelta(days=60)

    created = 0
    d = start
    while d <= today:
        existing = db.scalars(select(PumpLog).where(PumpLog.log_date == d)).first()
        if existing is None:
            db.add(PumpLog(log_date=d, runtime_hours=cfg.pump_timer_hours,
                           backwashed=0, source="auto"))
            created += 1
        d += timedelta(days=1)
    if created:
        db.commit()
    return created


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
