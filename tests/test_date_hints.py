"""DATE HINTS — must be consistent so compare_periods doesn't get different dates each call."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.ai.agent import _date_hints


def _retailer(tz: str = "UTC") -> dict:
    return {"id": "shop1", "timezone": tz}


def test_wednesday_anchors_last_weekend_to_previous_sat_sun():
    # 2026-05-27 is a Wednesday. Last weekend = Sat 2026-05-23, Sun 2026-05-24.
    now = datetime(2026, 5, 27, 12, 0, tzinfo=ZoneInfo("UTC"))
    h = _date_hints(_retailer(), now=now)
    assert h["today_iso"] == "2026-05-27"
    assert h["today_dow"] == "Wednesday"
    assert h["yesterday_iso"] == "2026-05-26"
    assert h["last_weekend_start"] == "2026-05-23"
    assert h["last_weekend_end"] == "2026-05-24"
    assert h["weekend_before_last_start"] == "2026-05-16"
    assert h["weekend_before_last_end"] == "2026-05-17"


def test_wednesday_calendar_weeks():
    now = datetime(2026, 5, 27, 12, 0, tzinfo=ZoneInfo("UTC"))
    h = _date_hints(_retailer(), now=now)
    # Mon 2026-05-25 → Sun 2026-05-31
    assert h["this_week_start"] == "2026-05-25"
    assert h["this_week_end"] == "2026-05-31"
    assert h["last_week_start"] == "2026-05-18"
    assert h["last_week_end"] == "2026-05-24"
    assert h["week_before_last_start"] == "2026-05-11"
    assert h["week_before_last_end"] == "2026-05-17"


def test_sunday_treats_today_as_part_of_last_weekend():
    # 2026-05-24 is a Sunday → "last weekend" should still be 2026-05-23/2026-05-24.
    now = datetime(2026, 5, 24, 12, 0, tzinfo=ZoneInfo("UTC"))
    h = _date_hints(_retailer(), now=now)
    assert h["last_weekend_start"] == "2026-05-23"
    assert h["last_weekend_end"] == "2026-05-24"


def test_month_boundaries():
    now = datetime(2026, 5, 27, 12, 0, tzinfo=ZoneInfo("UTC"))
    h = _date_hints(_retailer(), now=now)
    assert h["this_month_start"] == "2026-05-01"
    assert h["this_month_end"] == "2026-05-27"
    assert h["last_month_start"] == "2026-04-01"
    assert h["last_month_end"] == "2026-04-30"


def test_consistent_across_calls():
    """Same instant → same hints. This is the whole point — no drift."""
    now = datetime(2026, 5, 27, 12, 0, tzinfo=ZoneInfo("UTC"))
    h1 = _date_hints(_retailer(), now=now)
    h2 = _date_hints(_retailer(), now=now)
    assert h1 == h2


def test_bad_timezone_falls_back_to_utc():
    now = datetime(2026, 5, 27, 12, 0, tzinfo=ZoneInfo("UTC"))
    h = _date_hints({"id": "shop1", "timezone": "Not/A/Real/Zone"}, now=now)
    assert h["today_iso"] == "2026-05-27"
