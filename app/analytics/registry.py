"""Pluggable insight registry.

Adding a capability = drop one file in app/analytics/insights/ with an @insight function.
The engine auto-discovers it. This is the project's extensibility seam — keep it tiny.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable

import pandas as pd

Severity = str  # "info" | "warn" | "high"


@dataclasses.dataclass
class Insight:
    title: str
    severity: Severity          # info | warn | high  (high → escalated to proactive alert)
    metrics: dict[str, Any]     # ONLY engine-computed numbers — the trust contract
    finding: str                # one factual sentence; the narrator adds warmth
    name: str = ""              # filled in by the registry
    order: int = 100

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# fn(df, ctx) -> Insight | None
InsightFn = Callable[[pd.DataFrame, dict[str, Any]], "Insight | None"]
_REGISTRY: list[tuple[int, str, InsightFn]] = []


def insight(name: str, order: int = 100) -> Callable[[InsightFn], InsightFn]:
    def deco(fn: InsightFn) -> InsightFn:
        _REGISTRY.append((order, name, fn))
        return fn

    return deco


def registered() -> list[tuple[int, str, InsightFn]]:
    return sorted(_REGISTRY, key=lambda t: t[0])
