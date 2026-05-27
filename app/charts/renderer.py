"""Render insight metrics into WhatsApp-friendly PNG charts.

Headless matplotlib (Agg backend). Every function:
- takes the insight's `metrics` dict (already JSON-able, all numbers from the engine),
- returns raw PNG bytes,
- closes its figure in a `finally` so a long-running server doesn't leak.

Style is intentionally minimal — one accent colour, no legend clutter, big font.
A shop owner glancing at WhatsApp on a 5-inch screen should grasp the chart in <2s.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless; must be set before pyplot import
import matplotlib.pyplot as plt  # noqa: E402

ACCENT = "#0EA5E9"
CRITICAL = "#DC2626"
MUTED = "#94A3B8"
GOOD = "#16A34A"
BG = "#FFFFFF"
FIG_SIZE = (6.0, 4.0)
DPI = 120


def _new_fig():
    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=DPI, facecolor=BG)
    ax.set_facecolor(BG)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=11)
    return fig, ax


def _to_png(fig) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight", facecolor=BG)
    return buf.getvalue()


def _fmt_money(v: float, cur: str) -> str:
    return f"{cur} {v:,.0f}".strip()


def anomaly_spike(metrics: dict[str, Any]) -> bytes:
    """14-day daily revenue line with the anomaly day marked red."""
    series = metrics.get("daily_series") or []
    cur = metrics.get("currency", "")
    spike_day = metrics.get("date")
    fig, ax = _new_fig()
    try:
        if not series:
            ax.text(0.5, 0.5, "Not enough history yet", ha="center", va="center",
                    transform=ax.transAxes, fontsize=14, color=MUTED)
            ax.axis("off")
            return _to_png(fig)

        xs = [p["date"] for p in series]
        ys = [float(p["revenue"]) for p in series]
        ax.plot(range(len(xs)), ys, color=ACCENT, linewidth=2.2, marker="o",
                markersize=4, markerfacecolor=ACCENT, markeredgecolor=ACCENT)

        if spike_day and spike_day in xs:
            i = xs.index(spike_day)
            ax.plot(i, ys[i], "o", color=CRITICAL, markersize=12, zorder=5)
            ax.annotate(_fmt_money(ys[i], cur), xy=(i, ys[i]),
                        xytext=(0, 14), textcoords="offset points",
                        ha="center", fontsize=12, fontweight="bold", color=CRITICAL)

        ax.set_title(f"Revenue spike — {spike_day}", fontsize=14, fontweight="bold", loc="left")
        ax.set_ylabel(cur or "revenue", fontsize=11, color=MUTED)
        # show only a few date labels to avoid clutter
        step = max(1, len(xs) // 5)
        ax.set_xticks(range(0, len(xs), step))
        ax.set_xticklabels([xs[i][5:] for i in range(0, len(xs), step)], rotation=0)
        ax.grid(axis="y", alpha=0.25, linestyle="--")
        return _to_png(fig)
    finally:
        plt.close(fig)


def revenue_trend_line(metrics: dict[str, Any]) -> bytes:
    """Last 30 days revenue line with a faint mean line behind it."""
    series = metrics.get("daily_series") or []
    cur = metrics.get("currency", "")
    fig, ax = _new_fig()
    try:
        if not series:
            ax.text(0.5, 0.5, "Not enough history yet", ha="center", va="center",
                    transform=ax.transAxes, fontsize=14, color=MUTED)
            ax.axis("off")
            return _to_png(fig)

        xs = [p["date"] for p in series]
        ys = [float(p["revenue"]) for p in series]
        mean = sum(ys) / len(ys)

        ax.axhline(mean, color=MUTED, linewidth=1.2, linestyle="--", alpha=0.7)
        ax.plot(range(len(xs)), ys, color=ACCENT, linewidth=2.2)
        ax.fill_between(range(len(xs)), ys, alpha=0.12, color=ACCENT)

        delta = metrics.get("delta_pct", 0)
        arrow = "▲" if delta >= 0 else "▼"
        colour = GOOD if delta >= 0 else CRITICAL
        ax.set_title(f"30-day revenue  {arrow} {abs(delta):.0f}% vs avg",
                     fontsize=14, fontweight="bold", loc="left", color=colour)
        ax.set_ylabel(cur or "revenue", fontsize=11, color=MUTED)

        step = max(1, len(xs) // 5)
        ax.set_xticks(range(0, len(xs), step))
        ax.set_xticklabels([xs[i][5:] for i in range(0, len(xs), step)], rotation=0)
        ax.grid(axis="y", alpha=0.25, linestyle="--")
        return _to_png(fig)
    finally:
        plt.close(fig)


def wow_bars(metrics: dict[str, Any]) -> bytes:
    """Two bars: last week vs this week."""
    prev = float(metrics.get("prev_week_revenue", 0))
    this = float(metrics.get("this_week_revenue", 0))
    delta = float(metrics.get("delta_pct", 0))
    cur = metrics.get("currency", "")

    fig, ax = _new_fig()
    try:
        labels = ["Last week", "This week"]
        values = [prev, this]
        bars = ax.bar(labels, values, color=[MUTED, ACCENT], width=0.5)
        for bar, v in zip(bars, values):
            ax.annotate(_fmt_money(v, cur),
                        xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 6), textcoords="offset points",
                        ha="center", fontsize=12)
        arrow = "▲" if delta >= 0 else "▼"
        colour = GOOD if delta >= 0 else CRITICAL
        ax.set_title(f"Week over week  {arrow} {abs(delta):.0f}%",
                     fontsize=14, fontweight="bold", loc="left", color=colour)
        ax.set_ylabel(cur or "revenue", fontsize=11, color=MUTED)
        ax.set_ylim(0, max(values) * 1.25 if max(values) else 1)
        ax.grid(axis="y", alpha=0.25, linestyle="--")
        return _to_png(fig)
    finally:
        plt.close(fig)


def top_movers_bar(metrics: dict[str, Any]) -> bytes:
    """Horizontal bars: top 3 (green) on top, bottom 3 (gray) below."""
    top = metrics.get("top", []) or []
    slow = metrics.get("slow", []) or []
    cur = metrics.get("currency", "")

    fig, ax = _new_fig()
    try:
        items = [(p["product"], float(p["revenue"]), GOOD) for p in top] + \
                [(p["product"], float(p["revenue"]), MUTED) for p in slow]
        if not items:
            ax.text(0.5, 0.5, "No products to show", ha="center", va="center",
                    transform=ax.transAxes, fontsize=14, color=MUTED)
            ax.axis("off")
            return _to_png(fig)
        items.reverse()  # matplotlib draws bottom-up
        names = [t[0] for t in items]
        values = [t[1] for t in items]
        colours = [t[2] for t in items]
        bars = ax.barh(names, values, color=colours, height=0.6)
        for bar, v in zip(bars, values):
            ax.annotate(_fmt_money(v, cur),
                        xy=(bar.get_width(), bar.get_y() + bar.get_height() / 2),
                        xytext=(6, 0), textcoords="offset points",
                        va="center", fontsize=11)
        ax.set_title("Top & slow movers (14d)", fontsize=14, fontweight="bold", loc="left")
        ax.set_xlabel(cur or "revenue", fontsize=11, color=MUTED)
        ax.set_xlim(0, max(values) * 1.3 if max(values) else 1)
        ax.spines["bottom"].set_visible(False)
        ax.tick_params(axis="x", labelsize=10, colors=MUTED)
        return _to_png(fig)
    finally:
        plt.close(fig)
