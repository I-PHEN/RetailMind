"""Load the retailer registry (config/retailers.yaml) and provide lookups."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.settings import get_settings


@lru_cache
def _load() -> list[dict[str, Any]]:
    with open(get_settings().retailmind_config, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("retailers", [])


def all_retailers() -> list[dict[str, Any]]:
    return _load()


def get_retailer(retailer_id: str) -> dict[str, Any] | None:
    return next((r for r in _load() if r.get("id") == retailer_id), None)


def _digits(num: str) -> str:
    return "".join(ch for ch in num if ch.isdigit())


def by_whatsapp(number: str) -> dict[str, Any] | None:
    """Match an inbound Twilio 'From' (e.g. 'whatsapp:+2547...') to a retailer."""
    target = _digits(number)
    for r in _load():
        if _digits(r.get("whatsapp_to", "")) == target:
            return r
    return None
