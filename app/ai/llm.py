"""Single LLM entry point — Groq (OpenAI-compatible), one model.

Groq runs openai/gpt-oss-120b at ~250–500 tok/s, which makes tool-use loops
feel instant on WhatsApp. Provider and model live in `app/settings.py`.

We do one short retry on transient API errors (network blips); upstream
errors bubble up to the caller so it can show a user-friendly fallback.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from openai import APIError, OpenAI

from app.settings import get_settings

log = logging.getLogger("retailmind.llm")


@lru_cache
def _client() -> OpenAI:
    s = get_settings()
    # gpt-oss-120b is a reasoning model — give it generous headroom even though
    # Groq is usually <2s, so first-token / cold-cache turns don't time out.
    return OpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url,
                  max_retries=0, timeout=60.0)


def chat(messages: list[dict[str, Any]], tools: list[dict] | None = None,
         max_tokens: int = 700, reasoning_effort: str | None = "low") -> Any:
    """Return a ChatCompletion. Retries once on a transient APIError.

    `reasoning_effort` controls how many internal-reasoning tokens gpt-oss
    consumes before producing its visible answer. Default "low" keeps fast
    conversational turns from getting their tool call truncated. Pass
    `reasoning_effort=None` to let the model decide (defaults to high).
    """
    s = get_settings()
    kwargs: dict[str, Any] = {
        "model": s.llm_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
    if reasoning_effort and "gpt-oss" in s.llm_model:
        kwargs["reasoning_effort"] = reasoning_effort

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            return _client().chat.completions.create(**kwargs)
        except APIError as exc:
            last_err = exc
            log.warning("LLM call attempt %d failed: %s", attempt, exc)
            if attempt < 2:
                time.sleep(0.4)

    raise RuntimeError(f"LLM call failed after retries: {last_err}")
