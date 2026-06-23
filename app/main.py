"""FastAPI-App: Routen, Templates, Lebenszyklus."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import crud
from .checklists import CHECKLISTS
from .chemistry import (
    PARAMETERS, PURPOSES, cya_dilution_volume, evaluate,
    recommend_pump_runtime, shock_dose, _pick,
)
from .config import settings
from .database import Base, engine, get_db, migrate_schema
from .models import Measurement
from .mqtt import pool_mqtt

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_schema(engine)
    from .database import SessionLocal
    db = SessionLocal()
    try:
        crud.seed_defaults(db)
        # Automatisches Pumpen-Tracking nachholen (fehlende Tage füllen)
        crud.backfill_auto_pump_logs(db, crud.get_config(db))
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
    if value is None:
        return None
    value = value.strip().replace(",", ".")
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _ingress_base(request: Request) -> str:
    return request.headers.get("X-Ingress-Path", "").rstrip("/")


def _redirect(request: Request, path: str) -> RedirectResponse:
    return RedirectResponse(_ingress_base(request) + path, status_code=303)


def _base_context(request: Request) -> dict:
    return {
        "request": request,
        "app_name": settings.app_name,
        "mqtt_enabled": settings.mqtt_enabled,
        "parameters": PARAMETERS,
        "purposes": PURPOSES,
        "base": _ingress_base(request),
    }


# --------------------------------------------------------------------------
# Messung
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    cfg = crud.get_config(db)
    latest = crud.latest_measurement(db)
    chemicals = crud.list_chemicals(db, only_active=True)
    evaluation = evaluate(cfg, latest, chemicals) if latest else None
    dispenser = crud.get_dispenser(db)
    tab = crud.tab_status(dispenser)
    ctx = _base_context(request)
    ctx.update(config=cfg, latest=latest, evaluation=evaluation, saved=False,
               dispenser=dispenser, tab=tab)
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
    dispenser = crud.get_dispenser(db)
    tab = crud.tab_status(dispenser)
    ctx = _base_context(request)
    ctx.update(config=cfg, latest=measurement, evaluation=evaluation, saved=True,
               dispenser=dispenser, tab=tab)
    return templates.TemplateResponse("index.html", ctx)


@app.post("/dispenser/refill")
def dispenser_refill(request: Request, db: Session = Depends(get_db)):
    """Neuen Tab eingelegt – Einlege-Zeitpunkt auf jetzt setzen."""
    disp = crud.get_dispenser(db)
    crud.insert_fresh_tab(db, disp)
    return _redirect(request, "/")


@app.post("/dispenser/remove")
def dispenser_remove(request: Request, db: Session = Depends(get_db)):
    """Dosierer als leer markieren."""
    disp = crud.get_dispenser(db)
    crud.remove_tab(db, disp)
    return _redirect(request, "/")


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
def delete_measurement(measurement_id: int, request: Request, db: Session = Depends(get_db)):
    m = db.get(Measurement, measurement_id)
    if m:
        crud.delete_measurement(db, m)
    return _redirect(request, "/history")


# --------------------------------------------------------------------------
# Trendkurven
# --------------------------------------------------------------------------

@app.get("/trends", response_class=HTMLResponse)
def trends_page(request: Request, db: Session = Depends(get_db)):
    ctx = _base_context(request)
    return templates.TemplateResponse("trends.html", ctx)


@app.get("/api/trend-data")
def trend_data(db: Session = Depends(get_db)):
    measurements = crud.list_measurements_asc(db, limit=90)
    labels = [m.measured_at.strftime("%d.%m.%y") for m in measurements]
    return {
        "labels": labels,
        "ph": [m.ph for m in measurements],
        "free_cl": [m.free_cl for m in measurements],
        "ta": [m.ta for m in measurements],
        "cya": [m.cya for m in measurements],
        "temperature": [m.temperature for m in measurements],
    }


# --------------------------------------------------------------------------
# Pumpenlaufzeit
# --------------------------------------------------------------------------

@app.get("/pump-log", response_class=HTMLResponse)
def pump_log_page(request: Request, db: Session = Depends(get_db)):
    cfg = crud.get_config(db)
    # Fehlende Tage automatisch nachtragen (Timer-Tracking)
    crud.backfill_auto_pump_logs(db, cfg)
    logs = crud.list_pump_logs(db, limit=30)
    stats = crud.get_pump_stats(db, cfg.backwash_interval_hours)
    latest = crud.latest_measurement(db)
    temp = latest.temperature if latest else None
    recommendation = recommend_pump_runtime(cfg.volume_m3, cfg.pump_flow_m3h, temp)
    today = date.today()
    today_log = next((l for l in logs if l.log_date == today), None)
    ctx = _base_context(request)
    ctx.update(logs=logs, stats=stats, today=today, today_log=today_log,
               config=cfg, recommendation=recommendation, water_temp=temp)
    return templates.TemplateResponse("pump_log.html", ctx)


@app.post("/pump-log")
async def add_pump_log(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    log_date_str = form.get("log_date") or str(date.today())
    try:
        log_date = date.fromisoformat(log_date_str)
    except ValueError:
        log_date = date.today()
    hours = _parse_float(form.get("runtime_hours")) or 0.0
    backwashed = form.get("backwashed") == "on"
    note = (form.get("note") or "").strip() or None
    crud.log_pump(db, log_date, hours, backwashed, note, source="manual")
    return _redirect(request, "/pump-log")


@app.post("/pump-log/timer")
async def update_pump_timer(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cfg = crud.get_config(db)
    hours = _parse_float(form.get("pump_timer_hours"))
    if hours is not None:
        cfg.pump_timer_hours = hours
    cfg.pump_auto_track = 1 if form.get("pump_auto_track") else 0
    db.commit()
    crud.backfill_auto_pump_logs(db, cfg)
    return _redirect(request, "/pump-log")


@app.post("/pump-log/{log_id}/delete")
def delete_pump_log(log_id: int, request: Request, db: Session = Depends(get_db)):
    entry = crud.get_pump_log(db, log_id)
    if entry:
        crud.delete_pump_log(db, entry)
    return _redirect(request, "/pump-log")


# --------------------------------------------------------------------------
# Checklisten
# --------------------------------------------------------------------------

@app.get("/checklists", response_class=HTMLResponse)
def checklists_page(request: Request, db: Session = Depends(get_db)):
    active = crud.list_active_checklists(db)
    history_runs = crud.list_checklist_history(db, limit=5)
    checked_by_run: dict[int, set[str]] = {}
    for run in active:
        checked_by_run[run.id] = crud.get_checked_tasks(db, run.id)
    ctx = _base_context(request)
    ctx.update(
        checklists=CHECKLISTS,
        active_runs=active,
        history_runs=history_runs,
        checked_by_run=checked_by_run,
    )
    return templates.TemplateResponse("checklists.html", ctx)


@app.post("/checklists/start")
async def start_checklist(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cl_type = form.get("checklist_type") or "weekly"
    if cl_type in CHECKLISTS:
        crud.start_checklist(db, cl_type)
    return _redirect(request, "/checklists")


@app.post("/checklists/{run_id}/check/{task_key}")
def toggle_task(run_id: int, task_key: str, request: Request, db: Session = Depends(get_db)):
    run = crud.get_checklist_run(db, run_id)
    if run and run.completed_at is None:
        crud.toggle_task(db, run_id, task_key)
    return _redirect(request, "/checklists")


@app.post("/checklists/{run_id}/close")
def close_checklist(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = crud.get_checklist_run(db, run_id)
    if run:
        crud.close_checklist(db, run)
    return _redirect(request, "/checklists")


@app.post("/checklists/{run_id}/delete")
def delete_checklist(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = crud.get_checklist_run(db, run_id)
    if run:
        crud.delete_checklist(db, run)
    return _redirect(request, "/checklists")


# --------------------------------------------------------------------------
# Werkzeuge (Stoßchlorung, CYA-Rechner)
# --------------------------------------------------------------------------

@app.get("/tools", response_class=HTMLResponse)
def tools_page(request: Request, db: Session = Depends(get_db)):
    cfg = crud.get_config(db)
    latest = crud.latest_measurement(db)
    chemicals = crud.list_chemicals(db, only_active=True)
    shock_chems = [c for c in chemicals if c.purpose in ("chlorine_shock", "chlorine_free")]
    ctx = _base_context(request)
    ctx.update(config=cfg, latest=latest, shock_chems=shock_chems,
               shock_result=None, cya_result=None)
    return templates.TemplateResponse("tools.html", ctx)


@app.post("/tools/shock", response_class=HTMLResponse)
async def calc_shock(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cfg = crud.get_config(db)
    latest = crud.latest_measurement(db)
    chemicals = crud.list_chemicals(db, only_active=True)
    shock_chems = [c for c in chemicals if c.purpose in ("chlorine_shock", "chlorine_free")]

    chem_id = _parse_int(form.get("chem_id"), 0)
    current_fc = _parse_float(form.get("current_fc")) or 0.0
    target_fc = _parse_float(form.get("target_fc")) or 10.0
    vol = _parse_float(form.get("volume_m3")) or cfg.volume_m3

    selected_chem = next((c for c in shock_chems if c.id == chem_id), None) or (shock_chems[0] if shock_chems else None)

    shock_result = None
    if selected_chem:
        amount = shock_dose(selected_chem, current_fc, target_fc, vol)
        shock_result = {
            "chem": selected_chem,
            "amount": amount,
            "current_fc": current_fc,
            "target_fc": target_fc,
            "volume_m3": vol,
        }

    ctx = _base_context(request)
    ctx.update(config=cfg, latest=latest, shock_chems=shock_chems,
               shock_result=shock_result, cya_result=None,
               shock_form=dict(form))
    return templates.TemplateResponse("tools.html", ctx)


@app.post("/tools/cya", response_class=HTMLResponse)
async def calc_cya(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cfg = crud.get_config(db)
    latest = crud.latest_measurement(db)
    chemicals = crud.list_chemicals(db, only_active=True)
    shock_chems = [c for c in chemicals if c.purpose in ("chlorine_shock", "chlorine_free")]

    current_cya = _parse_float(form.get("current_cya")) or 0.0
    target_cya = _parse_float(form.get("target_cya")) or cfg.cya_dilution_target
    vol = _parse_float(form.get("volume_m3")) or cfg.volume_m3

    liters = cya_dilution_volume(current_cya, target_cya, vol)

    cya_result = {
        "current_cya": current_cya,
        "target_cya": target_cya,
        "volume_m3": vol,
        "liters_to_replace": liters,
        "fraction_pct": round((current_cya - target_cya) / current_cya * 100, 1) if current_cya > target_cya else 0,
    }

    ctx = _base_context(request)
    ctx.update(config=cfg, latest=latest, shock_chems=shock_chems,
               shock_result=None, cya_result=cya_result,
               cya_form=dict(form))
    return templates.TemplateResponse("tools.html", ctx)


# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------

@app.get("/config", response_class=HTMLResponse)
def config_page(request: Request, db: Session = Depends(get_db)):
    cfg = crud.get_config(db)
    chemicals = crud.list_chemicals(db)
    dispenser = crud.get_dispenser(db)
    ctx = _base_context(request)
    ctx.update(config=cfg, chemicals=chemicals, dispenser=dispenser, saved=False)
    return templates.TemplateResponse("config.html", ctx)


@app.post("/config")
async def update_config(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cfg = crud.get_config(db)
    float_fields = [
        "volume_m3", "pump_flow_m3h",
        "ph_min", "ph_target", "ph_max",
        "free_cl_min", "free_cl_target", "free_cl_max",
        "ta_min", "ta_target", "ta_max",
        "cya_min", "cya_target", "cya_max",
        "cya_warning_level", "cya_dilution_target", "backwash_interval_hours",
    ]
    for field in float_fields:
        val = _parse_float(form.get(field))
        if val is not None:
            setattr(cfg, field, val)
    name = (form.get("name") or "").strip()
    if name:
        cfg.name = name
    cfg.fc_min_dynamic = 1 if form.get("fc_min_dynamic") else 0
    db.commit()
    return _redirect(request, "/config")


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
    return _redirect(request, "/config")


@app.post("/config/chemicals/{chem_id}")
async def edit_chemical(chem_id: int, request: Request, db: Session = Depends(get_db)):
    chem = crud.get_chemical(db, chem_id)
    if chem is None:
        return _redirect(request, "/config")
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
    return _redirect(request, "/config")


@app.post("/config/chemicals/{chem_id}/delete")
def remove_chemical(chem_id: int, request: Request, db: Session = Depends(get_db)):
    chem = crud.get_chemical(db, chem_id)
    if chem:
        crud.delete_chemical(db, chem)
    return _redirect(request, "/config")


# --------------------------------------------------------------------------
# Lager / Vorrat
# --------------------------------------------------------------------------

@app.get("/inventory", response_class=HTMLResponse)
def inventory_page(request: Request, db: Session = Depends(get_db)):
    chemicals = crud.list_chemicals(db)
    low = crud.low_stock_chemicals(db)
    low_ids = {c.id for c in low}
    ctx = _base_context(request)
    ctx.update(chemicals=chemicals, low_ids=low_ids, low_count=len(low))
    return templates.TemplateResponse("inventory.html", ctx)


@app.post("/inventory/{chem_id}/set")
async def inventory_set(chem_id: int, request: Request, db: Session = Depends(get_db)):
    chem = crud.get_chemical(db, chem_id)
    if chem is None:
        return _redirect(request, "/inventory")
    form = await request.form()
    stock = _parse_float(form.get("stock_g"))
    min_stock = _parse_float(form.get("min_stock_g"))
    crud.update_chemical_stock(db, chem, stock, min_stock)
    return _redirect(request, "/inventory")


@app.post("/inventory/{chem_id}/adjust")
async def inventory_adjust(chem_id: int, request: Request, db: Session = Depends(get_db)):
    chem = crud.get_chemical(db, chem_id)
    if chem is None:
        return _redirect(request, "/inventory")
    form = await request.form()
    delta = _parse_float(form.get("delta")) or 0.0
    sign = form.get("sign", "minus")
    if sign == "minus":
        delta = -abs(delta)
    else:
        delta = abs(delta)
    crud.adjust_chemical_stock(db, chem, delta)
    return _redirect(request, "/inventory")


@app.post("/config/dispenser")
async def update_dispenser(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    disp = crud.get_dispenser(db)
    data = {}
    name = (form.get("name") or "").strip()
    if name:
        data["name"] = name
    tw = _parse_float(form.get("tablet_weight_g"))
    if tw is not None:
        data["tablet_weight_g"] = tw
    lifetime = _parse_float(form.get("tab_lifetime_days"))
    if lifetime is not None:
        data["tab_lifetime_days"] = lifetime
    count = _parse_int(form.get("current_count"), disp.current_count)
    data["current_count"] = max(1, count)
    if data:
        crud.update_dispenser(db, disp, data)
    return _redirect(request, "/config")


# --------------------------------------------------------------------------
# API / Health
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


@app.post("/api/measurements")
async def api_ingest(request: Request, db: Session = Depends(get_db),
                     x_api_key: str | None = Header(default=None)):
    """Nimmt Messwerte von externen Sonden (ESP32 etc.) per JSON entgegen.

    Beispiel-Body: {"ph": 7.21, "temperature": 26.4, "source": "esp32"}
    Ist POOL_INGEST_TOKEN gesetzt, muss der Header "X-API-Key" passen.
    """
    if settings.ingest_token and x_api_key != settings.ingest_token:
        return JSONResponse({"detail": "Ungültiger oder fehlender API-Key."}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"detail": "Ungültiges JSON."}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"detail": "JSON-Objekt erwartet."}, status_code=400)

    measurement = crud.ingest_measurement(db, payload)
    if measurement is None:
        return JSONResponse(
            {"detail": "Kein gültiger Messwert enthalten (ph, free_cl, total_cl, ta, cya, temperature)."},
            status_code=400,
        )
    pool_mqtt.publish_measurement(measurement)
    return JSONResponse({
        "status": "ok",
        "id": measurement.id,
        "measured_at": measurement.measured_at.isoformat(),
        "source": measurement.source,
    }, status_code=201)


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
