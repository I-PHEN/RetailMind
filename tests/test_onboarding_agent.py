"""Tests for the LLM-driven onboarding agent.

Mocks the LLM and verifies the agent: extracts via the single `act` tool,
sends OAuth when both fields are known, persists conversation history, and
falls back safely when the LLM returns plain content or no tool call.
"""
import json
from unittest.mock import MagicMock, patch


def _mk_tool_call(name: str, args: dict):
    """Build a tool_call object whose .function.name and .function.arguments
    are set correctly. (MagicMock(name=...) sets the mock's OWN name attribute,
    which collides — so we build a tiny object instead.)"""
    class _Fn:
        pass
    fn = _Fn()
    fn.name = name
    fn.arguments = json.dumps(args)
    tc = MagicMock()
    tc.function = fn
    return tc


def _llm_response(*tool_calls, content=None):
    msg = MagicMock(tool_calls=list(tool_calls), content=content)
    return MagicMock(choices=[MagicMock(message=msg)])


def test_agent_sends_only_reply_when_no_info_extracted():
    persist = MagicMock()
    sends: list[str] = []
    with patch("app.onboarding.agent.chat",
               return_value=_llm_response(
                   _mk_tool_call("act", {"reply": "Hey 👋 what should I call you?"}))), \
         patch("app.onboarding.agent.send_whatsapp",
               side_effect=lambda to, msg: sends.append(msg)):
        from app.onboarding.agent import respond
        respond("+234", "hi", {}, persist)

    persist.assert_called_once()
    step, data = persist.call_args[0]
    assert step == "awaiting_name"
    assert data["name"] is None
    assert data["shop_name"] is None
    assert sends == ["Hey 👋 what should I call you?"]
    assert data["history"][0] == {"role": "user", "content": "hi"}
    assert data["history"][-1]["role"] == "assistant"


def test_agent_extracts_name_and_asks_for_shop():
    persist = MagicMock()
    sends: list[str] = []
    with patch("app.onboarding.agent.chat",
               return_value=_llm_response(
                   _mk_tool_call("act", {
                       "name": "Michael",
                       "reply": "Nice Michael! What's your shop?",
                   }))), \
         patch("app.onboarding.agent.send_whatsapp",
               side_effect=lambda to, msg: sends.append(msg)):
        from app.onboarding.agent import respond
        respond("+234", "Hello I am Michael", {}, persist)

    step, data = persist.call_args[0]
    assert step == "awaiting_name"
    assert data["name"] == "Michael"
    assert data["shop_name"] is None
    assert "Michael" in sends[0]


def test_agent_sends_oauth_when_act_marks_send_link_true():
    persist = MagicMock()
    sends: list[str] = []
    with patch("app.onboarding.agent.chat",
               return_value=_llm_response(
                   _mk_tool_call("act", {
                       "shop": "Acme",
                       "send_oauth_link": True,
                       "reply": "Got it — Acme 🛒 Tap below.",
                   }))), \
         patch("app.onboarding.agent.send_whatsapp",
               side_effect=lambda to, msg: sends.append(msg)), \
         patch("app.onboarding.agent.send_whatsapp_link") as mock_link, \
         patch("app.onboarding.agent.send_typing"), \
         patch("app.onboarding.agent.build_oauth_url",
               return_value=("https://accounts.google.com/...", "tok123", "verifier-xyz")), \
         patch("app.onboarding.agent.get_settings",
               return_value=MagicMock(app_base_url="https://example.app")):
        from app.onboarding.agent import respond
        respond("+234", "Acme", {"name": "Michael"}, persist)

    step, data = persist.call_args[0]
    assert step == "awaiting_oauth"
    assert data["name"] == "Michael"
    assert data["shop_name"] == "Acme"
    assert data["oauth_state_token"] == "tok123"
    assert data["oauth_code_verifier"] == "verifier-xyz"  # required by Google PKCE
    assert data["oauth_auth_url"].startswith("https://accounts.google.com")
    assert len(data["short_token"]) == 8
    assert sends[0].startswith("Got it")
    mock_link.assert_called_once()
    short_url = mock_link.call_args[0][1]
    assert short_url == f"https://example.app/go/{data['short_token']}"


def test_agent_does_not_send_oauth_when_name_still_missing():
    """If the LLM mistakenly sets send_oauth_link=true without both fields, we don't send."""
    persist = MagicMock()
    sends: list[str] = []
    with patch("app.onboarding.agent.chat",
               return_value=_llm_response(
                   _mk_tool_call("act", {
                       "send_oauth_link": True,
                       "reply": "ok",
                   }))), \
         patch("app.onboarding.agent.send_whatsapp",
               side_effect=lambda to, msg: sends.append(msg)), \
         patch("app.onboarding.agent.send_whatsapp_link") as mock_link, \
         patch("app.onboarding.agent.build_oauth_url"):
        from app.onboarding.agent import respond
        respond("+234", "blah", {"name": "Michael"}, persist)

    mock_link.assert_not_called()
    step, _ = persist.call_args[0]
    assert step == "awaiting_name"


def test_agent_fallback_when_llm_fails():
    persist = MagicMock()
    sends: list[str] = []
    with patch("app.onboarding.agent.chat", side_effect=RuntimeError("LLM down")), \
         patch("app.onboarding.agent.send_whatsapp",
               side_effect=lambda to, msg: sends.append(msg)):
        from app.onboarding.agent import respond
        respond("+234", "hi", {}, persist)

    persist.assert_not_called()
    assert len(sends) == 1
    assert "issue" in sends[0].lower() or "moment" in sends[0].lower()


def test_agent_uses_plain_content_when_act_tool_not_called():
    """If the model returns plain text instead of calling `act`, we still ship it."""
    persist = MagicMock()
    sends: list[str] = []
    with patch("app.onboarding.agent.chat",
               return_value=_llm_response(content="Hey, what's your shop called?")), \
         patch("app.onboarding.agent.send_whatsapp",
               side_effect=lambda to, msg: sends.append(msg)):
        from app.onboarding.agent import respond
        respond("+234", "hi", {}, persist)

    assert len(sends) == 1
    assert sends[0] == "Hey, what's your shop called?"


def test_agent_uses_safe_fallback_when_llm_gives_nothing():
    """If the LLM returns no tool call and no content, fall back to a generic prompt."""
    persist = MagicMock()
    sends: list[str] = []
    with patch("app.onboarding.agent.chat",
               return_value=_llm_response(content=None)), \
         patch("app.onboarding.agent.send_whatsapp",
               side_effect=lambda to, msg: sends.append(msg)):
        from app.onboarding.agent import respond
        respond("+234", "hi", {}, persist)

    assert len(sends) == 1
    assert "again" in sends[0].lower()
