"""LLM-driven onboarding agent.

The agent owns the conversation while we're collecting the user's name and
shop name. It decides what to say, extracts info via tool calls, and triggers
the OAuth link send when ready. Replaces the hardcoded `awaiting_name` branch
of the old FSM.

Architecture: tool-use loop with three tools:
  - `remember(name?, shop?)` — persist what was extracted this turn
  - `send_oauth_link()` — flag that we should send the link this turn
  - `reply(message)` — the WhatsApp text to send to the user (terminal)

Conversation history is kept in onboarding_state.data["history"] so the LLM
sees what was said previously and doesn't loop or repeat questions.
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any

from app.ai.llm import chat
from app.messaging.wuzapi_client import send_typing, send_whatsapp, send_whatsapp_link
from app.onboarding.oauth import build_oauth_url
from app.settings import get_settings

log = logging.getLogger("retailmind.onboarding.agent")

# Cap history so each turn stays cheap. Most onboardings finish in <5 turns.
_HISTORY_MAX_TURNS = 12


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "act",
            "description": (
                "Decide and execute everything for this turn in ONE call. "
                "Always include `reply` (the WhatsApp message the user will see). "
                "If you newly learned the user's name or shop in this turn, "
                "include those fields. If you now have BOTH the user's name and "
                "shop name (from this turn OR remembered from before), set "
                "`send_oauth_link` to true so the system sends the connection link."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": ["string", "null"],
                        "description": "User's first name, if newly extracted from THIS turn. Null otherwise.",
                    },
                    "shop": {
                        "type": ["string", "null"],
                        "description": "User's shop/business name, if newly extracted from THIS turn. Null otherwise.",
                    },
                    "send_oauth_link": {
                        "type": "boolean",
                        "description": "True only when you have BOTH name AND shop (and haven't already sent the link).",
                    },
                    "reply": {
                        "type": "string",
                        "description": "The WhatsApp message to send. 1-2 short sentences. Warm, sharp, casual.",
                    },
                },
                "required": ["reply"],
            },
        },
    },
]


def _system_prompt(known: dict[str, Any]) -> str:
    name = known.get("name") or "(unknown)"
    shop = known.get("shop_name") or "(unknown)"
    return f"""You are RetailMind — an AI Chief Operating Officer for African small-shop owners, delivered over WhatsApp. You're meeting a new owner for the first time and getting them set up.

WHAT RETAILMIND ACTUALLY DOES (this is your real value — be ready to explain it)
You crunch the owner's actual sales data every morning and after every change. You spot what's selling fast, what's slowing down, what days are best/worst, who their top products are, and weird stuff that needs their attention (a price drop, a quiet day, a sudden spike). You don't just send numbers — you tell them what to DO about it. Think: a really sharp ops analyst who never sleeps, never forgets, and lives in their WhatsApp.

YOUR JOB IN THIS PARTICULAR CONVERSATION
Just two things:
  1. Get their first name AND their shop's name.
  2. When you have both, call `send_oauth_link` so they can connect their sales sheet.
That's it. Don't quiz them on what they sell or how big the shop is — that comes later, automatically, from their data.

WHAT YOU ALREADY KNOW
- Name: {name}
- Shop: {shop}

YOUR VOICE
Confident, sharp, warm. Like a senior operator who knows their stuff but isn't stiff. Short sentences. Casual but never sycophantic. You're comfortable with African retail — mini-marts, pharmacies, electronics shops, fashion, phones, provisions, beauty, fresh produce. If the user uses Pidgin or local turns of phrase, you can match a little; never lead with it.

REACT LIKE A HUMAN
When a shop name lands well, react: "iphEN — clean name 🔥", "Acme Electronics, nice." When someone tells you something unprompted ("I sell phones and chargers"), reflect it briefly — don't dig further. Pick your moments — don't react to every single thing.

HOW YOU RESPOND — IMPORTANT
You have ONE tool called `act`. Every turn, call `act` exactly once with:
- `reply`: the WhatsApp message to send (always required, 1–2 short sentences)
- `name`: only if you newly extracted it this turn (else omit / null)
- `shop`: only if you newly extracted it this turn (else omit / null)
- `send_oauth_link`: true only when you now have BOTH name AND shop

That single `act` call does everything for the turn.

CONVERSATION RULES
- NEVER ask for info you already have. If "WHAT YOU ALREADY KNOW" lists a name, don't ask for the name again.
- If only one is missing, acknowledge what they gave and ask for just the other.
- If they go off-topic (ask what you do, joke, etc.), give a quick honest answer, then steer back.
- Keep replies SHORT — 1–2 sentences. Light emoji (👋 🔥 ⚡ 📊) sparingly.
- NEVER invent info. If they say "Michael", don't assume their shop is "Michael's Shop". Wait for them to tell you.

EXAMPLE FIRST GREETING (nothing known yet)
act(reply="Hey 👋 I'm RetailMind — think of me as your shop's AI operations chief. Every day I'll read your sales data and tell you exactly what's working, what's not, and what to do about it. To set things up — what should I call you, and what's your shop called?")

EXAMPLE — USER GAVE NAME AND SHOP
User: "My name is Michael and my shop is iphEN"
→ act(name="Michael", shop="iphEN", send_oauth_link=true, reply="iphEN 🔥 Last step — tap the link below to connect your sales sheet and I'll get to work.")

EXAMPLE — USER ONLY GAVE NAME
User: "Hello I am Michael"
→ act(name="Michael", reply="Nice to meet you Michael 👋 And what's your shop called?")

EXAMPLE — USER SHOP KNOWN, NAME STILL MISSING
(WHAT YOU KNOW shows shop="iphEN", name unknown). User: "Acme"
→ act(name="Acme", send_oauth_link=true, reply="Got it Acme — iphEN it is 🔥 Tap the link below to connect your sheet.")

EXAMPLE — OFF-TOPIC QUESTION
User: "what do you actually do?"
→ act(reply="I read your sales data every day and ping you with what's moving, what's stalled, and what to do about it. Quick one — what should I call you?")

NEVER DO
- Dead corporate voice ("I would be delighted to assist...")
- Ask for name/shop again after they've given it
- Long paragraphs or numbered lists
- Calling yourself a chatbot or assistant — you're an AI COO
"""


def respond(whatsapp: str, text: str, current_data: dict[str, Any],
            persist_state: callable) -> None:
    """Run one agent turn. persist_state(step, data) is called to save the result."""
    history: list[dict[str, str]] = current_data.get("history", [])
    history.append({"role": "user", "content": text})

    messages = [{"role": "system", "content": _system_prompt(current_data)}, *history]
    try:
        # gpt-oss-120b reserves part of max_tokens for internal reasoning,
        # so we leave generous headroom for short conversational replies.
        resp = chat(messages=messages, tools=_TOOLS, max_tokens=800)
    except Exception:
        log.exception("LLM call failed; sending safe fallback")
        send_whatsapp(whatsapp,
                      "Sorry, I'm having a brief issue 🙏 Try sending again in a moment.")
        return

    msg_obj = resp.choices[0].message
    new_name = current_data.get("name")
    new_shop = current_data.get("shop_name")
    should_send_link = False
    reply_text: str | None = None

    # Expecting a single `act` tool call with everything in its args.
    for tc in (msg_obj.tool_calls or []):
        if tc.function.name != "act":
            continue
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        n, s = args.get("name"), args.get("shop")
        if isinstance(n, str) and n.strip():
            new_name = n.strip()
        if isinstance(s, str) and s.strip():
            new_shop = s.strip()
        if args.get("send_oauth_link") is True:
            should_send_link = True
        r = args.get("reply")
        if isinstance(r, str) and r.strip():
            reply_text = r.strip()

    # Fallback chain: if the model emitted plain content instead of `act`, use it.
    if not reply_text:
        plain = (msg_obj.content or "").strip()
        if plain:
            reply_text = plain
            log.info("LLM returned plain content instead of act tool; using it")
        else:
            reply_text = "Sorry, can you say that again?"
            log.warning(
                "LLM gave no reply at all. tool_calls=%r content=%r reasoning=%r",
                msg_obj.tool_calls, msg_obj.content,
                getattr(msg_obj, "reasoning", None),
            )

    history.append({"role": "assistant", "content": reply_text})
    history = history[-_HISTORY_MAX_TURNS * 2:]  # trim oldest turns

    new_data = {**current_data, "name": new_name, "shop_name": new_shop, "history": history}

    if should_send_link and new_name and new_shop:
        from app.onboarding.fsm import _detect_timezone, _detect_currency
        auth_url, state_token, code_verifier = build_oauth_url(whatsapp)
        short_token = secrets.token_hex(4)  # 8 hex chars → 32 bits entropy
        new_data.update({
            "oauth_state_token": state_token,
            "oauth_code_verifier": code_verifier,  # required by Google's PKCE
            "oauth_auth_url": auth_url,
            "short_token": short_token,
            "timezone": _detect_timezone(whatsapp),
            "currency": _detect_currency(whatsapp),
        })
        persist_state("awaiting_oauth", new_data)
        send_whatsapp(whatsapp, reply_text)
        # Show typing again so the link feels like a continuation of the reply,
        # not a separate / disconnected message.
        send_typing(whatsapp)
        short_url = f"{get_settings().app_base_url.rstrip('/')}/go/{short_token}"
        send_whatsapp_link(whatsapp, short_url, "Connect Google Sheet",
                           "Tap below to link your sales sheet ⚡")
    else:
        persist_state("awaiting_name", new_data)
        send_whatsapp(whatsapp, reply_text)
