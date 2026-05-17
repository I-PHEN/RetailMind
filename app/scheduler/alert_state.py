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
from pathlib import Path
from typing import Any

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
