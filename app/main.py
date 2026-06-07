"""FastAPI-App: Routen, Templates, Lebenszyklus."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import crud
from .chemistry import PARAMETERS, PURPOSES, evaluate
from .config import settings
from .database import Base, engine, get_db
from .models import Measurement
from .mqtt import pool_mqtt

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Erst-Befüllung
    from .database import SessionLocal
    db = SessionLocal()
    try:
        crud.seed_defaults(db)
    finally:
        db.close()
    pool_mqtt.start()
    yield
    pool_mqtt.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def _parse_float(value: str | None) -> float | None:
    """Wandelt Formularwert in float (akzeptiert Komma) oder None bei leer."""
    if value is None:
        return None
    value = value.strip().replace(",", ".")
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _base_context(request: Request) -> dict:
    return {
        "request": request,
        "app_name": settings.app_name,
        "mqtt_enabled": settings.mqtt_enabled,
        "parameters": PARAMETERS,
        "purposes": PURPOSES,
    }


# --------------------------------------------------------------------------
# Anwendungsseite: Messwerte erfassen & Dosiervorschlag
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    cfg = crud.get_config(db)
    latest = crud.latest_measurement(db)
    chemicals = crud.list_chemicals(db, only_active=True)
    evaluation = evaluate(cfg, latest, chemicals) if latest else None
    ctx = _base_context(request)
    ctx.update(config=cfg, latest=latest, evaluation=evaluation, saved=False)
    return templates.TemplateResponse("index.html", ctx)


@app.post("/measurements", response_class=HTMLResponse)
async def add_measurement(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = {
        "source": "manual",
        "ph": _parse_float(form.get("ph")),
        "free_cl": _parse_float(form.get("free_cl")),
        "total_cl": _parse_float(form.get("total_cl")),
        "ta": _parse_float(form.get("ta")),
        "cya": _parse_float(form.get("cya")),
        "temperature": _parse_float(form.get("temperature")),
        "note": (form.get("note") or "").strip() or None,
    }
    measured_at = form.get("measured_at")
    if measured_at:
        try:
            data["measured_at"] = datetime.fromisoformat(measured_at)
        except ValueError:
            pass

    measurement = crud.create_measurement(db, data)
    pool_mqtt.publish_measurement(measurement)

    cfg = crud.get_config(db)
    chemicals = crud.list_chemicals(db, only_active=True)
    evaluation = evaluate(cfg, measurement, chemicals)
    ctx = _base_context(request)
    ctx.update(config=cfg, latest=measurement, evaluation=evaluation, saved=True)
    return templates.TemplateResponse("index.html", ctx)


# --------------------------------------------------------------------------
# Verlauf
# --------------------------------------------------------------------------

@app.get("/history", response_class=HTMLResponse)
def history(request: Request, db: Session = Depends(get_db)):
    measurements = crud.list_measurements(db, limit=100)
    ctx = _base_context(request)
    ctx.update(measurements=measurements)
    return templates.TemplateResponse("history.html", ctx)


@app.post("/history/{measurement_id}/delete")
def delete_measurement(measurement_id: int, db: Session = Depends(get_db)):
    m = db.get(Measurement, measurement_id)
    if m:
        crud.delete_measurement(db, m)
    return RedirectResponse("/history", status_code=303)


# --------------------------------------------------------------------------
# Konfigurationsseite
# --------------------------------------------------------------------------

@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request, db: Session = Depends(get_db)):
    cfg = crud.get_config(db)
    chemicals = crud.list_chemicals(db)
    ctx = _base_context(request)
    ctx.update(config=cfg, chemicals=chemicals)
    return templates.TemplateResponse("config.html", ctx)


@app.post("/config")
async def update_config(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cfg = crud.get_config(db)
    fields = [
        "volume_m3", "pump_flow_m3h",
        "ph_min", "ph_target", "ph_max",
        "free_cl_min", "free_cl_target", "free_cl_max",
        "ta_min", "ta_target", "ta_max",
        "cya_min", "cya_target", "cya_max",
    ]
    for field in fields:
        val = _parse_float(form.get(field))
        if val is not None:
            setattr(cfg, field, val)
    name = (form.get("name") or "").strip()
    if name:
        cfg.name = name
    db.commit()
    return RedirectResponse("/config", status_code=303)


@app.post("/config/chemicals")
async def add_chemical(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    purpose = form.get("purpose") or "other"
    data = {
        "name": (form.get("name") or "Neue Chemikalie").strip(),
        "purpose": purpose,
        "unit": form.get("unit") or PURPOSES.get(purpose, {}).get("unit", "g"),
        "ref_dose_amount": _parse_float(form.get("ref_dose_amount")) or 100.0,
        "ref_volume_m3": _parse_float(form.get("ref_volume_m3")) or 10.0,
        "ref_effect_delta": _parse_float(form.get("ref_effect_delta")) or 0.0,
        "active_ingredient_pct": _parse_float(form.get("active_ingredient_pct")),
        "notes": (form.get("notes") or "").strip() or None,
        "is_active": 1,
    }
    crud.create_chemical(db, data)
    return RedirectResponse("/config", status_code=303)


@app.post("/config/chemicals/{chem_id}")
async def edit_chemical(chem_id: int, request: Request, db: Session = Depends(get_db)):
    chem = crud.get_chemical(db, chem_id)
    if chem is None:
        return RedirectResponse("/config", status_code=303)
    form = await request.form()
    data = {
        "name": (form.get("name") or chem.name).strip(),
        "purpose": form.get("purpose") or chem.purpose,
        "unit": form.get("unit") or chem.unit,
        "ref_dose_amount": _parse_float(form.get("ref_dose_amount")) or chem.ref_dose_amount,
        "ref_volume_m3": _parse_float(form.get("ref_volume_m3")) or chem.ref_volume_m3,
        "ref_effect_delta": _parse_float(form.get("ref_effect_delta")) or 0.0,
        "active_ingredient_pct": _parse_float(form.get("active_ingredient_pct")),
        "notes": (form.get("notes") or "").strip() or None,
        "is_active": 1 if form.get("is_active") else 0,
    }
    crud.update_chemical(db, chem, data)
    return RedirectResponse("/config", status_code=303)


@app.post("/config/chemicals/{chem_id}/delete")
def remove_chemical(chem_id: int, db: Session = Depends(get_db)):
    chem = crud.get_chemical(db, chem_id)
    if chem:
        crud.delete_chemical(db, chem)
    return RedirectResponse("/config", status_code=303)


# --------------------------------------------------------------------------
# API / Health (für Home Assistant REST-Sensor & Monitoring)
# --------------------------------------------------------------------------

@app.get("/api/latest")
def api_latest(db: Session = Depends(get_db)):
    m = crud.latest_measurement(db)
    if m is None:
        return JSONResponse({"detail": "Noch keine Messwerte vorhanden."}, status_code=404)
    return {
        "measured_at": m.measured_at.isoformat(),
        "source": m.source,
        "ph": m.ph,
        "free_cl": m.free_cl,
        "total_cl": m.total_cl,
        "ta": m.ta,
        "cya": m.cya,
        "temperature": m.temperature,
    }


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
