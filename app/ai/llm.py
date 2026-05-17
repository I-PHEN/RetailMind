"""Single LLM entry point — OpenAI-compatible client (OpenRouter by default).

Both the narrator and the agent go through here so the provider/model is one config change.

Free OpenRouter models get rate-limited upstream without warning. To keep a live demo from
dying, `chat()` tries the configured model and, on a 429 / provider error, immediately falls
back to the next free model in the chain rather than waiting or crashing.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from openai import APIError, APIStatusError, OpenAI, RateLimitError

from app.settings import get_settings

log = logging.getLogger("retailmind.llm")

# Free, tool-capable fallbacks (live on OpenRouter as of build). The configured
# LLM_MODEL is tried first; these are tried in order if it's unavailable.
FALLBACK_MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "openai/gpt-oss-120b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "z-ai/glm-4.5-air:free",
    "deepseek/deepseek-v4-flash:free",
]


@lru_cache
def _client() -> OpenAI:
    s = get_settings()
    # We handle fallback ourselves; don't let the SDK silently retry the same model.
    return OpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url, max_retries=0)


def chat(messages: list[dict[str, Any]], tools: list[dict] | None = None,
         max_tokens: int = 700) -> Any:
    """Return a ChatCompletion, transparently failing over across free models."""
    s = get_settings()
    chain: list[str] = [s.llm_model] + [m for m in FALLBACK_MODELS if m != s.llm_model]

    last_err: Exception | None = None
    for model in chain:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "extra_headers": {"X-Title": "RetailMind"},
        }
        if tools:
            kwargs["tools"] = tools
        try:
            resp = _client().chat.completions.create(**kwargs)
            if model != s.llm_model:
                log.warning("LLM fell back to %s (primary unavailable)", model)
            return resp
        except (RateLimitError, APIStatusError) as exc:  # 429 / 5xx → try next model
            last_err = exc
            log.warning("model %s unavailable (%s); trying next", model,
                        getattr(exc, "status_code", "?"))
            time.sleep(0.5)
        except APIError as exc:  # transient network/provider error → one quick retry
            last_err = exc
            log.warning("model %s API error: %s; trying next", model, exc)
            time.sleep(0.5)

    raise RuntimeError(
        f"All free models unavailable right now (last error: {last_err}). "
        "Retry in a moment or set LLM_MODEL to a different OpenRouter model."
    )
