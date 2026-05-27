"""Alert pause: owner says 'quiet for N hours' → poll returns nothing."""
from datetime import datetime, timedelta, timezone

from app.scheduler import alert_state as st
from app.scheduler.alert_policy import select_candidates


def _retailer(rid: str = "shop1") -> dict:
    return {"id": rid, "name": "Shop", "currency": "GHS",
            "timezone": "UTC", "quiet_hours": "00:00-00:00"}


def _critical_anomaly() -> dict:
    return {"name": "anomaly", "severity": "high", "title": "Spike",
            "finding": "x", "metrics": {"z_score": 5.0}}


def test_is_paused_true_inside_window_false_after_expiry():
    state: dict = {}
    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    st.set_pause(state, "shop1", (now + timedelta(hours=2)).isoformat(), "busy")
    assert st.is_paused(state, "shop1", now=now) is True
    assert st.is_paused(state, "shop1", now=now + timedelta(hours=3)) is False


def test_select_candidates_returns_empty_when_paused_even_for_critical():
    state: dict = {}
    retailer = _retailer()
    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    st.set_pause(state, "shop1", (now + timedelta(hours=2)).isoformat())
    bundle = {"insights": [_critical_anomaly()]}
    assert select_candidates(bundle, retailer, state, now=now) == []


def test_clear_pause_removes_entry():
    state: dict = {}
    now = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    st.set_pause(state, "shop1", (now + timedelta(hours=1)).isoformat())
    st.clear_pause(state, "shop1")
    assert st.is_paused(state, "shop1", now=now) is False
