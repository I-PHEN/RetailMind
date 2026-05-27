"""Persistent per-retailer alert memory (survives restarts).

Stored as JSON at data/runtime/alert_state.json (data/runtime/ is gitignored). This is what
lets the policy say "I already alerted this, and it hasn't worsened" instead of re-spamming.

Shape:
{
  "<retailer_id>": {
     "<insight_name>": {"severity": "high", "key": 4.0, "last_sent_iso": "..."}
  },
  "_digest": {"<retailer_id>": {"at_iso": "...", "names": ["wow_change", ...]}}
}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dateutil import parser as dateparser

log = logging.getLogger("retailmind.alert_state")

_PATH = Path("data/runtime/alert_state.json")


def load_state() -> dict[str, Any]:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"_digest": {}}
    except Exception:
        log.exception("alert_state unreadable; starting fresh")
        return {"_digest": {}}


def save_state(state: dict[str, Any]) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except Exception:
        log.exception("could not persist alert_state")


def get_insight_state(state: dict, retailer_id: str, name: str) -> dict | None:
    return state.get(retailer_id, {}).get(name)


def set_insight_state(state: dict, retailer_id: str, name: str,
                      severity: str, key: float, sent_iso: str) -> None:
    state.setdefault(retailer_id, {})[name] = {
        "severity": severity,
        "key": key,
        "last_sent_iso": sent_iso,
    }


def record_digest(state: dict, retailer_id: str, at_iso: str, names: list[str]) -> None:
    state.setdefault("_digest", {})[retailer_id] = {"at_iso": at_iso, "names": names}


def last_digest(state: dict, retailer_id: str) -> dict | None:
    return state.get("_digest", {}).get(retailer_id)


def set_pause(state: dict, retailer_id: str, until_iso: str,
              reason: str | None = None) -> None:
    """Tell the alerter to stay quiet for this retailer until `until_iso`."""
    state.setdefault("_pause", {})[retailer_id] = {
        "until_iso": until_iso,
        "reason": (reason or "").strip() or None,
    }


def clear_pause(state: dict, retailer_id: str) -> None:
    state.get("_pause", {}).pop(retailer_id, None)


def is_paused(state: dict, retailer_id: str, now: datetime | None = None) -> bool:
    entry = state.get("_pause", {}).get(retailer_id)
    if not entry or not entry.get("until_iso"):
        return False
    try:
        until = dateparser.parse(entry["until_iso"])
    except Exception:
        return False
    now = now or datetime.now(timezone.utc)
    return now < until


def mark_acknowledged(state: dict, retailer_id: str, at_iso: str) -> int:
    """When the retailer messages us, treat it as 'I've seen everything you sent'.

    Bumps every active insight's last_sent_iso to `at_iso` so the cooldown clock
    restarts from THEIR action, not ours. Returns the count of insights touched.
    """
    bucket = state.get(retailer_id) or {}
    touched = 0
    for name, payload in bucket.items():
        if isinstance(payload, dict) and payload.get("last_sent_iso"):
            payload["last_sent_iso"] = at_iso
            touched += 1
    return touched
