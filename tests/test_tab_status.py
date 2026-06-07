"""Tests für die Chlor-Tab-Reststatus-Berechnung."""

from datetime import datetime, timedelta, timezone

from app.crud import tab_status
from app.models import TabletDispenser


def _disp(last_refill_at=None, lifetime=10.0, count=1):
    return TabletDispenser(
        id=1, name="Test", tablet_weight_g=200.0, current_count=count,
        last_refill_at=last_refill_at, tab_lifetime_days=lifetime,
    )


def test_no_tab_inserted():
    assert tab_status(_disp(last_refill_at=None))["inserted"] is False


def test_fresh_tab_has_full_lifetime_left():
    now = datetime.now(timezone.utc)
    st = tab_status(_disp(last_refill_at=now, lifetime=10.0))
    assert st["inserted"] is True
    assert st["depleted"] is False
    assert 9.9 <= st["days_left"] <= 10.0
    assert st["days_used"] == 0


def test_tab_partially_used():
    inserted = datetime.now(timezone.utc) - timedelta(days=6)
    st = tab_status(_disp(last_refill_at=inserted, lifetime=10.0))
    assert st["days_used"] == 6
    assert 3.9 <= st["days_left"] <= 4.1
    assert st["depleted"] is False


def test_tab_depleted():
    inserted = datetime.now(timezone.utc) - timedelta(days=12)
    st = tab_status(_disp(last_refill_at=inserted, lifetime=10.0))
    assert st["depleted"] is True
    assert st["days_left"] < 0


def test_naive_datetime_is_handled():
    # SQLite kann naive Zeitstempel liefern -> darf nicht crashen
    inserted = datetime.utcnow() - timedelta(days=3)
    st = tab_status(_disp(last_refill_at=inserted, lifetime=10.0))
    assert st["inserted"] is True
    assert st["days_used"] == 3
