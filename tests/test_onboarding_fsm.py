from unittest.mock import MagicMock, patch


def _mock_supabase(state_row=None):
    """Return a mock Supabase client with controllable query results."""
    sb = MagicMock()
    # onboarding_state table
    state_table = MagicMock()
    sb.table.return_value = state_table
    select_chain = MagicMock()
    state_table.select.return_value = select_chain
    eq_chain = MagicMock()
    select_chain.eq.return_value = eq_chain
    eq_chain.execute.return_value = MagicMock(data=[state_row] if state_row else [])
    # upsert/delete chains
    state_table.upsert.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))
    state_table.delete.return_value = MagicMock(eq=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=None))))
    return sb


def test_first_message_sends_greeting():
    sb = _mock_supabase(state_row=None)
    with patch("app.onboarding.fsm._get_supabase", return_value=sb), \
         patch("app.onboarding.fsm.send_whatsapp") as mock_send:
        from app.onboarding.fsm import handle
        handle("+2348012345678", "Hi RetailMind")
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "RetailMind" in msg
        assert "name" in msg.lower()


def test_awaiting_name_sends_oauth_link():
    state_row = {
        "whatsapp": "+2348012345678",
        "step": "awaiting_name",
        "data": {},
    }
    sb = _mock_supabase(state_row=state_row)
    with patch("app.onboarding.fsm._get_supabase", return_value=sb), \
         patch("app.onboarding.fsm.send_whatsapp") as mock_send, \
         patch("app.onboarding.fsm.send_whatsapp_link") as mock_link, \
         patch("app.onboarding.fsm.build_oauth_url", return_value=("https://oauth.url", "tok123")):
        from app.onboarding.fsm import handle
        handle("+2348012345678", "I'm Amina, Amina's Mini-Mart")
        mock_link.assert_called_once()
        args = mock_link.call_args[0]
        assert args[0] == "+2348012345678"
        assert args[1] == "https://oauth.url"


def test_awaiting_oauth_sends_reminder():
    state_row = {
        "whatsapp": "+2348012345678",
        "step": "awaiting_oauth",
        "data": {"name": "Amina", "shop_name": "Amina's Mini-Mart", "oauth_state_token": "tok"},
    }
    sb = _mock_supabase(state_row=state_row)
    with patch("app.onboarding.fsm._get_supabase", return_value=sb), \
         patch("app.onboarding.fsm.send_whatsapp") as mock_send:
        from app.onboarding.fsm import handle
        handle("+2348012345678", "hello?")
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "link" in msg.lower() or "connect" in msg.lower()
