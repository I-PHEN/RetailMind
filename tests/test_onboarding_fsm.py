"""Tests for the FSM dispatcher.

The FSM now delegates the awaiting_name step to the LLM-driven agent
(see tests/test_onboarding_agent.py for that). This file just verifies routing.
"""
from unittest.mock import MagicMock, patch


def _mock_supabase(state_row=None):
    sb = MagicMock()
    state_table = MagicMock()
    sb.table.return_value = state_table
    state_table.select.return_value.eq.return_value.execute.return_value = \
        MagicMock(data=[state_row] if state_row else [])
    state_table.upsert.return_value.execute.return_value = MagicMock(data=[])
    state_table.delete.return_value.eq.return_value.execute.return_value = None
    return sb


def test_first_contact_routes_to_agent_with_empty_data():
    sb = _mock_supabase(state_row=None)
    with patch("app.onboarding.fsm._get_supabase", return_value=sb), \
         patch("app.onboarding.fsm.onboarding_agent.respond") as mock_respond:
        from app.onboarding.fsm import handle
        handle("+2348012345678", "hi there")
        mock_respond.assert_called_once()
        kwargs = mock_respond.call_args.kwargs
        assert kwargs["whatsapp"] == "+2348012345678"
        assert kwargs["text"] == "hi there"
        assert kwargs["current_data"] == {}


def test_awaiting_name_routes_to_agent_with_existing_data():
    state_row = {
        "whatsapp": "+2348012345678",
        "step": "awaiting_name",
        "data": {"name": "Amina", "history": [{"role": "user", "content": "hi"}]},
    }
    sb = _mock_supabase(state_row=state_row)
    with patch("app.onboarding.fsm._get_supabase", return_value=sb), \
         patch("app.onboarding.fsm.onboarding_agent.respond") as mock_respond:
        from app.onboarding.fsm import handle
        handle("+2348012345678", "Amina's Mini-Mart")
        mock_respond.assert_called_once()
        assert mock_respond.call_args.kwargs["current_data"]["name"] == "Amina"


def test_awaiting_oauth_sends_reminder():
    state_row = {
        "whatsapp": "+2348012345678",
        "step": "awaiting_oauth",
        "data": {"name": "Amina", "shop_name": "Amina's Mini-Mart"},
    }
    sb = _mock_supabase(state_row=state_row)
    with patch("app.onboarding.fsm._get_supabase", return_value=sb), \
         patch("app.onboarding.fsm.send_whatsapp") as mock_send, \
         patch("app.onboarding.fsm.onboarding_agent.respond") as mock_respond:
        from app.onboarding.fsm import handle
        handle("+2348012345678", "hello?")
        mock_respond.assert_not_called()
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "link" in msg.lower() or "connect" in msg.lower()


def test_awaiting_sheet_pick_sends_reminder():
    state_row = {
        "whatsapp": "+2348012345678",
        "step": "awaiting_sheet_pick",
        "data": {"google_token": {"access_token": "x"}},
    }
    sb = _mock_supabase(state_row=state_row)
    with patch("app.onboarding.fsm._get_supabase", return_value=sb), \
         patch("app.onboarding.fsm.send_whatsapp") as mock_send:
        from app.onboarding.fsm import handle
        handle("+2348012345678", "?")
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "sheet" in msg.lower()
