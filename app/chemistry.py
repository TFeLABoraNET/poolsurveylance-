"""Pool-Chemie: Bewertung der Messwerte, Dosiervorschläge und Berechnungen.

Die Berechnungen sind bewusst einfach gehalten und basieren auf der
Referenz-Dosierung der jeweiligen Chemikalie (so wie sie auf der
Verpackung steht). Sie sind als *Schätzung / Startwert* gedacht –
gib lieber etwas weniger zu, lass die Umwälzpumpe laufen und miss nach.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Chemical, Measurement, PoolConfig

# ---------------------------------------------------------------------------
# Stammdaten: Einsatzzwecke und Parameter
# ---------------------------------------------------------------------------

PURPOSES: dict[str, dict] = {
    "ph_minus": {"label": "pH-Minus (pH senken)", "unit": "g", "default_effect": 0.1},
    "ph_plus": {"label": "pH-Plus (pH heben)", "unit": "g", "default_effect": 0.1},
    "chlorine_free": {"label": "Chlor (freies Chlor heben)", "unit": "g", "default_effect": 1.0},
    "chlorine_shock": {"label": "Chlor-Schock / Stoßchlorung", "unit": "g", "default_effect": 1.0},
    "alkalinity_plus": {"label": "Alkalinität-Plus (TA heben)", "unit": "g", "default_effect": 10.0},
    "stabilizer": {"label": "Stabilisator (Cyanursäure heben)", "unit": "g", "default_effect": 10.0},
    "algaecide": {"label": "Algizid (Algenschutz)", "unit": "ml", "default_effect": 0.0},
    "flocculant": {"label": "Flockmittel", "unit": "ml", "default_effect": 0.0},
    "other": {"label": "Sonstiges", "unit": "g", "default_effect": 0.0},
}

PARAMETERS: dict[str, dict] = {
    "ph": {"label": "pH-Wert", "unit": "", "decimals": 1},
    "free_cl": {"label": "Freies Chlor", "unit": "mg/l", "decimals": 1},
    "total_cl": {"label": "Gesamtchlor", "unit": "mg/l", "decimals": 1},
    "ta": {"label": "Gesamtalkalinität (TA)", "unit": "mg/l", "decimals": 0},
    "cya": {"label": "Cyanursäure (Stabilisator)", "unit": "mg/l", "decimals": 0},
    "temperature": {"label": "Wassertemperatur", "unit": "°C", "decimals": 1},
}


# ---------------------------------------------------------------------------
# Ergebnis-Strukturen
# ---------------------------------------------------------------------------

@dataclass
class ParameterStatus:
    key: str
    label: str
    unit: str
    value: float | None
    target: float | None
    range_min: float | None
    range_max: float | None
    status: str  # "ok" | "low" | "high" | "unknown"

    @property
    def status_label(self) -> str:
        return {
            "ok": "Im Sollbereich",
            "low": "Zu niedrig",
            "high": "Zu hoch",
            "unknown": "Kein Messwert",
        }[self.status]


@dataclass
class DosingSuggestion:
    parameter: str
    purpose: str
    chemical_name: str
    amount: float
    unit: str
    reason: str
    delta: float


@dataclass
class Evaluation:
    statuses: list[ParameterStatus] = field(default_factory=list)
    suggestions: list[DosingSuggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    turnover_hours: float | None = None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _classify(value: float | None, lo: float, hi: float) -> str:
    if value is None:
        return "unknown"
    if value < lo:
        return "low"
    if value > hi:
        return "high"
    return "ok"


def required_dose(chem: Chemical, delta: float, volume_m3: float) -> float:
    """Menge der Chemikalie, um den Parameter um ``delta`` zu ändern.

    Formel: menge = (delta / ref_effect) * (volume / ref_volume) * ref_dose
    """
    if chem.ref_effect_delta <= 0 or chem.ref_volume_m3 <= 0:
        return 0.0
    return max(0.0, (delta / chem.ref_effect_delta) * (volume_m3 / chem.ref_volume_m3) * chem.ref_dose_amount)


def _pick(chemicals: list[Chemical], purpose: str) -> Chemical | None:
    for c in chemicals:
        if c.purpose == purpose and c.is_active and c.ref_effect_delta > 0:
            return c
    return None


def _round_dose(amount: float) -> float:
    if amount < 50:
        return round(amount)
    if amount < 500:
        return round(amount / 5) * 5
    return round(amount / 10) * 10


def effective_fc_min(cfg: PoolConfig, cya_val: float | None) -> float:
    """Effektives Chlor-Minimum: bei aktiviertem dynamischem Modus CYA × 7,5 %."""
    if cfg.fc_min_dynamic and cya_val and cya_val > 0:
        return max(cfg.free_cl_min or 1.0, cya_val * 0.075)
    return cfg.free_cl_min or 1.0


def cya_dilution_volume(current_cya: float, target_cya: float, pool_volume_m3: float) -> float:
    """Liter Wasser, die getauscht werden müssen, um CYA von current auf target zu senken.

    Formel: V_tausch = (current - target) / current × pool_volume_m3 × 1000
    """
    if current_cya <= 0 or target_cya >= current_cya:
        return 0.0
    fraction = (current_cya - target_cya) / current_cya
    return round(fraction * pool_volume_m3 * 1000)


def shock_dose(chem: Chemical, current_fc: float, target_fc: float, volume_m3: float) -> float:
    """Menge Schockprodukt, um freies Chlor von current_fc auf target_fc zu heben."""
    delta = max(0.0, target_fc - current_fc)
    return _round_dose(required_dose(chem, delta, volume_m3))


def recommend_pump_runtime(volume_m3: float, flow_m3h: float,
                           temperature: float | None = None) -> dict:
    """Empfohlene tägliche Pumpenlaufzeit.

    Kombiniert zwei gängige Faustregeln:

    * **Umwälzung:** Das Beckenwasser sollte pro Tag etwa 2× komplett umgewälzt
      werden. Umwälzzeit = Volumen / Durchfluss; Empfehlung = 2 × Umwälzzeit.
    * **Temperaturregel:** Laufzeit (h) ≈ Wassertemperatur (°C) / 2. Je wärmer
      das Wasser, desto mehr Filterung/Chlorbedarf.

    Empfohlen wird der höhere der beiden Werte (auf halbe Stunden gerundet,
    sinnvoll begrenzt auf 4–16 h/Tag).
    """
    result: dict = {}
    candidates: list[float] = []

    if flow_m3h and flow_m3h > 0 and volume_m3 > 0:
        turnover = volume_m3 / flow_m3h
        result["turnover_hours"] = round(turnover, 1)
        two_turnovers = round(turnover * 2 * 2) / 2  # auf 0,5 h runden
        result["two_turnovers"] = two_turnovers
        candidates.append(two_turnovers)

    if temperature is not None:
        temp_rule = round(temperature / 2 * 2) / 2
        result["temp_rule"] = temp_rule
        candidates.append(temp_rule)

    if candidates:
        rec = max(candidates)
        rec = max(4.0, min(16.0, rec))  # sinnvoll begrenzen
        result["recommended"] = round(rec * 2) / 2

    return result


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def evaluate(cfg: PoolConfig, m: Measurement, chemicals: list[Chemical]) -> Evaluation:
    """Bewertet einen Messwert-Satz und erzeugt Dosiervorschläge."""
    ev = Evaluation()

    if cfg.pump_flow_m3h and cfg.pump_flow_m3h > 0:
        ev.turnover_hours = round(cfg.volume_m3 / cfg.pump_flow_m3h, 1)

    fc_min = effective_fc_min(cfg, m.cya)

    ev.statuses = [
        ParameterStatus("ph", PARAMETERS["ph"]["label"], "", m.ph,
                        cfg.ph_target, cfg.ph_min, cfg.ph_max,
                        _classify(m.ph, cfg.ph_min, cfg.ph_max)),
        ParameterStatus("free_cl", PARAMETERS["free_cl"]["label"], "mg/l", m.free_cl,
                        cfg.free_cl_target, fc_min, cfg.free_cl_max,
                        _classify(m.free_cl, fc_min, cfg.free_cl_max)),
        ParameterStatus("ta", PARAMETERS["ta"]["label"], "mg/l", m.ta,
                        cfg.ta_target, cfg.ta_min, cfg.ta_max,
                        _classify(m.ta, cfg.ta_min, cfg.ta_max)),
        ParameterStatus("cya", PARAMETERS["cya"]["label"], "mg/l", m.cya,
                        cfg.cya_target, cfg.cya_min, cfg.cya_max,
                        _classify(m.cya, cfg.cya_min, cfg.cya_max)),
    ]
    if m.temperature is not None:
        ev.statuses.append(
            ParameterStatus("temperature", PARAMETERS["temperature"]["label"], "°C",
                            m.temperature, None, None, None, "ok")
        )

    vol = cfg.volume_m3

    # --- Gesamtalkalinität zuerst ---
    if m.ta is not None and m.ta < cfg.ta_min:
        chem = _pick(chemicals, "alkalinity_plus")
        delta = cfg.ta_target - m.ta
        if chem:
            amount = _round_dose(required_dose(chem, delta, vol))
            if amount > 0:
                ev.suggestions.append(DosingSuggestion(
                    parameter=PARAMETERS["ta"]["label"], purpose="alkalinity_plus",
                    chemical_name=chem.name, amount=amount, unit=chem.unit, delta=delta,
                    reason=f"TA von {m.ta:g} auf ~{cfg.ta_target:g} mg/l anheben. "
                           "Stabilisiert den pH-Wert – am besten zuerst korrigieren.",
                ))
        else:
            ev.warnings.append("Keine Chemikalie für 'Alkalinität-Plus' konfiguriert.")
    elif m.ta is not None and m.ta > cfg.ta_max:
        ev.warnings.append(
            f"TA ist mit {m.ta:g} mg/l zu hoch. TA senkt man üblicherweise mit pH-Minus "
            "(in mehreren kleinen Schritten). Bitte schrittweise vorgehen und nachmessen."
        )

    # --- pH ---
    if m.ph is not None and m.ph > cfg.ph_max:
        chem = _pick(chemicals, "ph_minus")
        delta = m.ph - cfg.ph_target
        if chem:
            amount = _round_dose(required_dose(chem, delta, vol))
            if amount > 0:
                ev.suggestions.append(DosingSuggestion(
                    parameter=PARAMETERS["ph"]["label"], purpose="ph_minus",
                    chemical_name=chem.name, amount=amount, unit=chem.unit, delta=-delta,
                    reason=f"pH von {m.ph:g} auf ~{cfg.ph_target:g} senken.",
                ))
        else:
            ev.warnings.append("Keine Chemikalie für 'pH-Minus' konfiguriert.")
    elif m.ph is not None and m.ph < cfg.ph_min:
        chem = _pick(chemicals, "ph_plus")
        delta = cfg.ph_target - m.ph
        if chem:
            amount = _round_dose(required_dose(chem, delta, vol))
            if amount > 0:
                ev.suggestions.append(DosingSuggestion(
                    parameter=PARAMETERS["ph"]["label"], purpose="ph_plus",
                    chemical_name=chem.name, amount=amount, unit=chem.unit, delta=delta,
                    reason=f"pH von {m.ph:g} auf ~{cfg.ph_target:g} anheben.",
                ))
        else:
            ev.warnings.append("Keine Chemikalie für 'pH-Plus' konfiguriert.")

    # --- Freies Chlor ---
    if m.free_cl is not None and m.free_cl < fc_min:
        purpose = "chlorine_free"
        chem = _pick(chemicals, purpose)
        if chem is None:
            purpose = "chlorine_shock"
            chem = _pick(chemicals, purpose)
        delta = cfg.free_cl_target - m.free_cl
        if chem:
            amount = _round_dose(required_dose(chem, delta, vol))
            if amount > 0:
                hint = ""
                if m.free_cl < 0.3:
                    hint = " Chlor ist sehr niedrig – eine Stoßchlorung kann sinnvoll sein."
                ev.suggestions.append(DosingSuggestion(
                    parameter=PARAMETERS["free_cl"]["label"], purpose=purpose,
                    chemical_name=chem.name, amount=amount, unit=chem.unit, delta=delta,
                    reason=f"Freies Chlor von {m.free_cl:g} auf ~{cfg.free_cl_target:g} mg/l "
                           f"anheben.{hint}",
                ))
        else:
            ev.warnings.append("Keine Chemikalie für 'Chlor' konfiguriert.")
    elif m.free_cl is not None and m.free_cl > cfg.free_cl_max:
        ev.warnings.append(
            f"Freies Chlor ist mit {m.free_cl:g} mg/l zu hoch. Kein Chlor zugeben, "
            "Becken meiden bis der Wert fällt (Sonne/Umwälzung bauen Chlor ab)."
        )

    # --- Gebundenes Chlor (Chloramine) ---
    if m.free_cl is not None and m.total_cl is not None:
        combined = m.total_cl - m.free_cl
        if combined > 0.5:
            ev.warnings.append(
                f"Gebundenes Chlor (Chloramine) ~{combined:.1f} mg/l ist erhöht "
                f"(> 0,5 mg/l). Eine Stoßchlorung ('Superchlorung') wird empfohlen."
            )

    # --- Cyanursäure / Stabilisator ---
    if m.cya is not None and m.cya < cfg.cya_min:
        chem = _pick(chemicals, "stabilizer")
        delta = cfg.cya_target - m.cya
        if chem:
            amount = _round_dose(required_dose(chem, delta, vol))
            if amount > 0:
                ev.suggestions.append(DosingSuggestion(
                    parameter=PARAMETERS["cya"]["label"], purpose="stabilizer",
                    chemical_name=chem.name, amount=amount, unit=chem.unit, delta=delta,
                    reason=f"Stabilisator (Cyanursäure) von {m.cya:g} auf ~{cfg.cya_target:g} "
                           "mg/l anheben. Schützt das Chlor vor UV-Abbau.",
                ))
    elif m.cya is not None and m.cya > (cfg.cya_warning_level or 70.0):
        liters = cya_dilution_volume(m.cya, cfg.cya_dilution_target, cfg.volume_m3)
        ev.warnings.append(
            f"Cyanursäure ist mit {m.cya:g} mg/l sehr hoch (> {cfg.cya_warning_level:g} mg/l). "
            f"Das schwächt die Chlorwirkung erheblich. "
            f"Empfehlung: ca. {liters:,.0f} Liter Wasser tauschen, um CYA auf "
            f"~{cfg.cya_dilution_target:g} mg/l zu senken."
        )

    # --- Dynamisches Chlor-Minimum Hinweis ---
    if cfg.fc_min_dynamic and m.cya and m.cya > 0:
        dyn_min = m.cya * 0.075
        if dyn_min > cfg.free_cl_min:
            ev.warnings.append(
                f"Dynamisches Chlor-Minimum aktiv: Bei CYA = {m.cya:g} mg/l sollte "
                f"das freie Chlor mind. {dyn_min:.1f} mg/l betragen (7,5 % von CYA)."
            )

    if ev.suggestions:
        ev.warnings.append(
            "Reihenfolge: erst TA, dann pH, dann Chlor. Mengen sind Schätzwerte – "
            "lieber etwas weniger zugeben, Umwälzpumpe laufen lassen und nachmessen."
        )

    return ev
