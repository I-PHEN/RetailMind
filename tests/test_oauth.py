from unittest.mock import MagicMock, patch
import pytest


def _mock_settings():
    return MagicMock(
        google_oauth_client_id="client_id",
        google_oauth_client_secret="client_secret",
        google_oauth_redirect_uri="https://app.example.com/auth/google/callback",
    )


def test_build_oauth_url_contains_state():
    with patch("app.onboarding.oauth.get_settings", return_value=_mock_settings()):
        from app.onboarding.oauth import build_oauth_url
        url, state_token = build_oauth_url("+2348012345678")
        assert "accounts.google.com" in url
        assert state_token in url
        assert len(state_token) == 32  # 16 bytes hex


def test_build_oauth_url_has_sheets_scope():
    with patch("app.onboarding.oauth.get_settings", return_value=_mock_settings()):
        from app.onboarding.oauth import build_oauth_url
        url, _ = build_oauth_url("+2348012345678")
        assert "spreadsheets.readonly" in url


def test_state_token_is_unique():
    with patch("app.onboarding.oauth.get_settings", return_value=_mock_settings()):
        from app.onboarding.oauth import build_oauth_url
        _, t1 = build_oauth_url("+234...")
        _, t2 = build_oauth_url("+234...")
        assert t1 != t2


def test_complete_onboarding_creates_retailer_and_sends_digest():
    fake_tokens = {
        "access_token": "acc",
        "refresh_token": "ref",
        "expiry": None,
        "client_id": "cid",
        "client_secret": "cs",
    }
    fake_state_row = {
        "whatsapp": "+2348012345678",
        "step": "awaiting_oauth",
        "data": {
            "name": "Amina",
            "shop_name": "Amina's Mini-Mart",
            "oauth_state_token": "tok123",
            "timezone": "Africa/Lagos",
        },
    }
    sb = MagicMock()
    # state lookup by token
    select_chain = MagicMock()
    sb.table.return_value.select.return_value.filter.return_value.execute.return_value = \
        MagicMock(data=[fake_state_row])
    sb.table.return_value.insert.return_value.execute.return_value = \
        MagicMock(data=[{"id": "amina_minimart"}])
    sb.table.return_value.delete.return_value.eq.return_value.execute.return_value = None

    with patch("app.onboarding.oauth.exchange_code", return_value=fake_tokens), \
         patch("app.onboarding.oauth._get_supabase", return_value=sb), \
         patch("app.retailers.create_retailer", return_value={"id": "amina_minimart", "whatsapp": "+2348012345678"}), \
         patch("app.messaging.evolution_client.send_whatsapp") as mock_send, \
         patch("app.pipeline.run_digest") as mock_digest:
        from app.onboarding.oauth import complete_onboarding
        complete_onboarding(code="authcode123", state_token="tok123")
        mock_send.assert_called()
        mock_digest.assert_called_once()
