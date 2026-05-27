"""Cooldown + acknowledgment behavior — guards the 'don't spam the owner' contract."""
from datetime import datetime, timedelta, timezone

import pytest

from app.scheduler import alert_state as st
from app.scheduler.alert_policy import (
    CRITICAL_COOLDOWN_H,
    DEFAULT_COOLDOWN_H,
    select_candidates,
)


def _anomaly_insight(z_score: float, severity: str = "high") -> dict:
    return {
        "name": "anomaly",
        "severity": severity,
        "title": "Sales spike",
        "finding": "spike",
        "metrics": {"z_score": z_score},
    }


def _retailer(rid: str = "shop1") -> dict:
    return {
        "id": rid,
        "name": "Shop",
        "currency": "GHS",
        "timezone": "UTC",
        "alert_cooldown_hours": DEFAULT_COOLDOWN_H,
        "quiet_hours": "00:00-00:00",  # disable quiet-hours for tests
    }


def _now() -> datetime:
    # 12:00 UTC — well outside the default quiet window
    return datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)


def test_critical_anomaly_does_not_bypass_cooldown_forever():
    """The 'sent every poll' bug: critical alerts must still respect a minimum cooldown."""
    state: dict = {}
    retailer = _retailer()
    bundle = {"insights": [_anomaly_insight(z_score=5.0)]}  # critical (>=4.0)

    # First poll: new -> fires.
    cands = select_candidates(bundle, retailer, state, now=_now())
    assert len(cands) == 1
    st.set_insight_state(
        state, "shop1", "anomaly", "high", 5.0, _now().isoformat()
    )

    # 5 minutes later — within critical cooldown (1h). Must NOT re-fire.
    poll2 = _now() + timedelta(minutes=5)
    bundle2 = {"insights": [_anomaly_insight(z_score=5.0)]}
    assert select_candidates(bundle2, retailer, state, now=poll2) == []

    # 30 min later — still within 1h critical cooldown.
    poll3 = _now() + timedelta(minutes=30)
    assert select_candidates(bundle2, retailer, state, now=poll3) == []

    # 65 min later — past critical cooldown AND key didn't worsen >50% -> still suppressed.
    poll4 = _now() + timedelta(minutes=65)
    assert select_candidates(bundle2, retailer, state, now=poll4) == []


def test_critical_re_fires_after_cooldown_if_materially_worse():
    state: dict = {}
    retailer = _retailer()
    st.set_insight_state(
        state, "shop1", "anomaly", "high", 5.0, _now().isoformat()
    )

    # Past cooldown, key grew by 60% (>50% threshold).
    poll = _now() + timedelta(minutes=70)
    bundle = {"insights": [_anomaly_insight(z_score=8.0)]}
    cands = select_candidates(bundle, retailer, state, now=poll)
    assert len(cands) == 1
    assert cands[0][1] == "worsened"


def test_worsening_threshold_is_high_enough_to_avoid_drift():
    """A 20% jump (within poll-to-poll noise) must NOT re-fire."""
    state: dict = {}
    retailer = _retailer()
    st.set_insight_state(
        state, "shop1", "anomaly", "high", 5.0, _now().isoformat()
    )
    poll = _now() + timedelta(hours=2)  # well past critical cooldown
    bundle = {"insights": [_anomaly_insight(z_score=6.0)]}  # 20% bigger
    assert select_candidates(bundle, retailer, state, now=poll) == []


def test_mark_acknowledged_bumps_active_alerts():
    state: dict = {}
    earlier = _now() - timedelta(minutes=30)
    st.set_insight_state(state, "shop1", "anomaly", "high", 5.0, earlier.isoformat())
    st.set_insight_state(state, "shop1", "low_stock", "high", 2.0, earlier.isoformat())

    new_ts = _now().isoformat()
    touched = st.mark_acknowledged(state, "shop1", new_ts)
    assert touched == 2
    assert state["shop1"]["anomaly"]["last_sent_iso"] == new_ts
    assert state["shop1"]["low_stock"]["last_sent_iso"] == new_ts


def test_ack_extends_cooldown_so_next_poll_stays_quiet():
    """After the owner replies, the next anomaly poll must not immediately re-fire."""
    state: dict = {}
    retailer = _retailer()
    # Alert was sent 30 minutes ago.
    sent_at = _now() - timedelta(minutes=30)
    st.set_insight_state(state, "shop1", "anomaly", "high", 5.0, sent_at.isoformat())

    # Owner reads + replies NOW -> ack bumps the clock.
    st.mark_acknowledged(state, "shop1", _now().isoformat())

    # Next poll runs 5 minutes after ack — must stay quiet (well inside cooldown).
    poll = _now() + timedelta(minutes=5)
    bundle = {"insights": [_anomaly_insight(z_score=5.0)]}
    assert select_candidates(bundle, retailer, state, now=poll) == []
