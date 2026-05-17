"""Importing this package registers every insight via its @insight decorator.

To add a capability: create app/analytics/insights/<name>.py and import it here.
"""
from app.analytics.insights import (  # noqa: F401
    anomaly,
    best_worst_days,
    low_stock,
    revenue_trend,
    top_bottom_sellers,
    wow_change,
)
