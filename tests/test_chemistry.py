"""Tests für die Dosier-Logik."""

from app.chemistry import evaluate, required_dose
from app.models import Chemical, Measurement, PoolConfig


def _config(volume=10.0):
    return PoolConfig(
        id=1, name="Test", volume_m3=volume, pump_flow_m3h=5.0,
        ph_min=7.0, ph_target=7.2, ph_max=7.4,
        free_cl_min=1.0, free_cl_target=1.5, free_cl_max=3.0,
        ta_min=80.0, ta_target=100.0, ta_max=120.0,
        cya_min=30.0, cya_target=40.0, cya_max=50.0,
    )


def _ph_minus():
    return Chemical(id=1, name="pH-Minus", purpose="ph_minus", unit="g",
                    ref_dose_amount=100, ref_volume_m3=10, ref_effect_delta=0.1, is_active=1)


def _ph_plus():
    return Chemical(id=2, name="pH-Plus", purpose="ph_plus", unit="g",
                    ref_dose_amount=100, ref_volume_m3=10, ref_effect_delta=0.1, is_active=1)


def _chlorine():
    return Chemical(id=3, name="Chlor", purpose="chlorine_free", unit="g",
                    ref_dose_amount=17, ref_volume_m3=10, ref_effect_delta=1.0, is_active=1)


def test_required_dose_scales_with_volume_and_delta():
    chem = _ph_minus()
    # 100 g / 10 m³ / 0,1 pH  ->  bei 20 m³ und 0,2 pH = 4x = 400 g
    assert required_dose(chem, delta=0.2, volume_m3=20.0) == 400.0


def test_required_dose_zero_when_no_effect():
    chem = Chemical(id=9, name="x", purpose="other", unit="g",
                    ref_dose_amount=100, ref_volume_m3=10, ref_effect_delta=0.0)
    assert required_dose(chem, delta=1.0, volume_m3=10.0) == 0.0


def test_ph_high_suggests_ph_minus():
    cfg = _config(volume=10.0)
    m = Measurement(id=1, ph=7.8, free_cl=1.5, ta=100, cya=40)
    ev = evaluate(cfg, m, [_ph_minus(), _ph_plus(), _chlorine()])
    ph_sugs = [s for s in ev.suggestions if s.purpose == "ph_minus"]
    assert len(ph_sugs) == 1
    # Senkung 7,8 -> 7,2 = 0,6 ; 100 g/10m³/0,1 -> 600 g
    assert ph_sugs[0].amount == 600


def test_ph_low_suggests_ph_plus():
    cfg = _config()
    m = Measurement(id=1, ph=6.8, free_cl=1.5, ta=100, cya=40)
    ev = evaluate(cfg, m, [_ph_minus(), _ph_plus()])
    assert any(s.purpose == "ph_plus" for s in ev.suggestions)


def test_low_chlorine_suggests_chlorine():
    cfg = _config()
    m = Measurement(id=1, ph=7.2, free_cl=0.5, ta=100, cya=40)
    ev = evaluate(cfg, m, [_chlorine()])
    cl = [s for s in ev.suggestions if s.purpose == "chlorine_free"]
    assert len(cl) == 1
    # 0,5 -> 1,5 = 1,0 mg/l ; 17 g/10m³/1,0 -> 17 g
    assert cl[0].amount == 17


def test_all_in_range_no_suggestions():
    cfg = _config()
    m = Measurement(id=1, ph=7.2, free_cl=1.5, ta=100, cya=40)
    ev = evaluate(cfg, m, [_ph_minus(), _ph_plus(), _chlorine()])
    assert ev.suggestions == []


def test_combined_chlorine_warning():
    cfg = _config()
    m = Measurement(id=1, ph=7.2, free_cl=1.5, total_cl=2.5, ta=100, cya=40)
    ev = evaluate(cfg, m, [_chlorine()])
    assert any("Chloramine" in w for w in ev.warnings)


def test_missing_values_are_unknown():
    cfg = _config()
    m = Measurement(id=1)  # keine Werte
    ev = evaluate(cfg, m, [])
    statuses = {s.key: s.status for s in ev.statuses}
    assert statuses["ph"] == "unknown"
    assert ev.suggestions == []
