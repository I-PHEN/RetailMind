"""Chart-policy rules — which insights earn a chart, which don't."""
from unittest.mock import patch

from app.charts.policy import chart_for, pick_chart_for_message

PNG = b"\x89PNG\r\n\x1a\nstub"


def _ins(name, severity="info", **metrics):
    return {"name": name, "severity": severity, "title": name, "finding": "", "metrics": metrics}


def test_anomaly_always_charts_when_severity_high():
    # render is mocked — we only assert the policy GATE here
    with patch("app.charts.policy.renderer.anomaly_spike", return_value=PNG):
        assert chart_for(_ins("anomaly", "high", z_score=3.5, daily_series=[])) == PNG
        assert chart_for(_ins("anomaly", "warn", z_score=2.1, daily_series=[])) == PNG


def test_wow_change_charts_only_when_delta_big_enough():
    with patch("app.charts.policy.renderer.wow_bars", return_value=PNG):
        assert chart_for(_ins("wow_change", delta_pct=25.0)) == PNG
        assert chart_for(_ins("wow_change", delta_pct=-20.0)) == PNG
        assert chart_for(_ins("wow_change", delta_pct=10.0)) is None
        assert chart_for(_ins("wow_change", delta_pct=14.9)) is None


def test_revenue_trend_charts_only_on_meaningful_delta():
    with patch("app.charts.policy.renderer.revenue_trend_line", return_value=PNG):
        assert chart_for(_ins("revenue_trend", delta_pct=30.0, daily_series=[])) == PNG
        assert chart_for(_ins("revenue_trend", delta_pct=-26.0, daily_series=[])) == PNG
        # 24% delta — flat-ish line, prose handles it better
        assert chart_for(_ins("revenue_trend", delta_pct=24.0, daily_series=[])) is None


def test_low_stock_never_charts():
    # Even with high severity and rich data: low_stock is a list, not a trend.
    assert chart_for(_ins("low_stock", "high",
                          items=[{"product": "X", "days_to_reorder": 1}])) is None


def test_top_movers_chart_only_on_real_outlier():
    with patch("app.charts.policy.renderer.top_movers_bar", return_value=PNG):
        # top is ~5x median — clear outlier
        outlier = _ins("top_bottom_sellers",
                       top=[{"product": "A", "revenue": 1000}],
                       slow=[{"product": "B", "revenue": 200},
                             {"product": "C", "revenue": 150}])
        assert chart_for(outlier) == PNG
        # top ~1.2x median — boring, no chart
        flat = _ins("top_bottom_sellers",
                    top=[{"product": "A", "revenue": 240}],
                    slow=[{"product": "B", "revenue": 200},
                          {"product": "C", "revenue": 180}])
        assert chart_for(flat) is None


def test_unknown_insight_name_never_charts():
    assert chart_for(_ins("totally_made_up", "high")) is None


def test_pick_chart_for_message_prefers_high_severity():
    """Given a mix, the highest-severity chart-eligible insight wins."""
    with patch("app.charts.policy.renderer.anomaly_spike", return_value=b"\x89PNGanomaly"), \
         patch("app.charts.policy.renderer.wow_bars", return_value=b"\x89PNGwow"):
        insights = [
            _ins("wow_change", "warn", delta_pct=20.0),       # eligible, warn
            _ins("anomaly", "high", z_score=3.5, daily_series=[]),  # eligible, high
        ]
        pick = pick_chart_for_message(insights)
        assert pick is not None
        ins, png = pick
        assert ins["name"] == "anomaly"
        assert png == b"\x89PNGanomaly"


def test_pick_chart_for_message_returns_none_when_nothing_qualifies():
    insights = [
        _ins("low_stock", "high"),
        _ins("wow_change", delta_pct=5.0),  # below 15
    ]
    assert pick_chart_for_message(insights) is None


def test_pick_chart_for_message_empty_input():
    assert pick_chart_for_message([]) is None
