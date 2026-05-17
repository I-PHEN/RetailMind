"""LLM #1 — the alert gatekeeper.

It runs AFTER the deterministic policy and may only NARROW the candidate list (drop redundant
items, merge) and write a short headline. It cannot add items, change numbers, or invent
urgency. It is FAIL-OPEN: any error / bad output / model down → send every rule-validated
candidate. The LLM can only ever reduce noise, never silence a real alert.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ai.llm import chat

log = logging.getLogger("retailmind.alert_judge")

SYSTEM_PROMPT = """You are RetailMind's alert gatekeeper. A deterministic engine has ALREADY \
detected and rule-validated the candidate alerts below. Your only job: decide which genuinely \
deserve interrupting a busy shop owner on WhatsApp *right now*, and write one short headline.

You MUST NOT:
- add any item not in the candidates,
- change, recompute, or invent any number,
- invent urgency that the data/reason does not support.

You MAY ONLY: keep an item, drop an item as redundant or not-worth-interrupting, and write a
headline. If the owner's morning digest already told them something and it has NOT worsened, \
that is a good reason to drop it (it is not new news). When unsure, KEEP high-severity items \
— missing a real alert is worse than one extra.

Output ONLY strict minified JSON, no prose:
{"send":["insight_name",...],"dropped":[{"name":"...","reason":"..."}],"headline":"<=12 words"}
"""


def _fallback(candidates: list[tuple[dict, str]]) -> dict[str, Any]:
    names = [ins["name"] for ins, _ in candidates]
    top = max(candidates, key=lambda c: c[0].get("severity") == "high")
    return {"send": names, "dropped": [], "headline": top[0].get("title", "Heads up")}


def judge(candidates: list[tuple[dict, str]], digest_summary: list[str],
          retailer: dict) -> dict[str, Any]:
    if not candidates:
        return {"send": [], "dropped": [], "headline": ""}

    payload = {
        "shop": retailer.get("name", ""),
        "already_told_in_todays_digest": digest_summary,
        "candidates": [
            {"name": ins["name"], "severity": ins["severity"], "reason": reason,
             "finding": ins["finding"], "metrics": ins.get("metrics", {})}
            for ins, reason in candidates
        ],
    }
    valid_names = {ins["name"] for ins, _ in candidates}

    try:
        resp = chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
            max_tokens=300,
        )
        raw = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("no JSON in judge output")
        data = json.loads(m.group(0))

        # Enforce the contract: judge may only choose among the given candidates.
        send = [n for n in data.get("send", []) if n in valid_names]
        if not send:
            log.info("judge dropped all candidates for %s: %s",
                     retailer["id"], data.get("dropped"))
            return {"send": [], "dropped": data.get("dropped", []), "headline": ""}
        return {
            "send": send,
            "dropped": data.get("dropped", []),
            "headline": str(data.get("headline", "")).strip(),
        }
    except Exception:
        log.exception("judge failed — failing open (sending all rule-validated candidates)")
        return _fallback(candidates)
