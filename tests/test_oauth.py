from unittest.mock import MagicMock, patch
import pytest


def _mock_settings():
    return MagicMock(
        google_oauth_client_id="client_id",
        google_oauth_client_secret="client_secret",
        google_oauth_redirect_uri="https://app.example.com/auth/google/callback",
        google_api_key="picker_api_key",
    )


def test_build_oauth_url_contains_state():
    with patch("app.onboarding.oauth.get_settings", return_value=_mock_settings()):
        from app.onboarding.oauth import build_oauth_url
        url, state_token, _ = build_oauth_url("+2348012345678")
        assert "accounts.google.com" in url
        assert state_token in url
        assert len(state_token) == 32  # 16 bytes hex


def test_build_oauth_url_has_sheets_and_drive_file_scopes():
    with patch("app.onboarding.oauth.get_settings", return_value=_mock_settings()):
        from app.onboarding.oauth import build_oauth_url
        url, _, _ = build_oauth_url("+2348012345678")
        assert "spreadsheets.readonly" in url
        assert "drive.file" in url


def test_build_oauth_url_includes_pkce_challenge():
    """PKCE: auth URL must carry a code_challenge derived from our verifier."""
    with patch("app.onboarding.oauth.get_settings", return_value=_mock_settings()):
        from app.onboarding.oauth import build_oauth_url
        url, _, verifier = build_oauth_url("+2348012345678")
        assert verifier  # non-empty
        assert "code_challenge" in url
        assert "code_challenge_method=S256" in url


def test_state_token_and_verifier_are_unique_per_call():
    with patch("app.onboarding.oauth.get_settings", return_value=_mock_settings()):
        from app.onboarding.oauth import build_oauth_url
        _, t1, v1 = build_oauth_url("+234...")
        _, t2, v2 = build_oauth_url("+234...")
        assert t1 != t2
        assert v1 != v2


def _fake_tokens():
    return {
        "access_token": "acc", "refresh_token": "ref", "expiry": None,
        "client_id": "cid", "client_secret": "cs",
    }


def _fake_state_row():
    return {
        "whatsapp": "+2348012345678",
        "step": "awaiting_oauth",
        "data": {
            "name": "Amina",
            "shop_name": "Amina's Mini-Mart",
            "oauth_state_token": "tok123",
            "oauth_code_verifier": "the-pkce-verifier",
            "timezone": "Africa/Lagos",
            "currency": "NGN",
        },
    }


def test_handle_oauth_callback_advances_to_awaiting_sheet_pick():
    sb = MagicMock()
    sb.table.return_value.select.return_value.filter.return_value.execute.return_value = \
        MagicMock(data=[_fake_state_row()])
    sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

    with patch("app.onboarding.oauth.exchange_code",
               return_value=_fake_tokens()) as mock_exchange, \
         patch("app.onboarding.oauth._get_supabase", return_value=sb):
        from app.onboarding.oauth import handle_oauth_callback
        whatsapp, access_token = handle_oauth_callback(code="x", state_token="tok123")
        assert whatsapp == "+2348012345678"
        assert access_token == "acc"
        # PKCE: must forward the saved code_verifier to exchange_code
        mock_exchange.assert_called_once_with("x", code_verifier="the-pkce-verifier")
        upsert_payload = sb.table.return_value.upsert.call_args[0][0]
        assert upsert_payload["step"] == "awaiting_sheet_pick"
        assert upsert_payload["data"]["google_token"]["access_token"] == "acc"


def test_finalize_with_sheet_creates_retailer_with_spreadsheet_id():
    row = _fake_state_row()
    row["step"] = "awaiting_sheet_pick"
    row["data"]["google_token"] = _fake_tokens()

    sb = MagicMock()
    sb.table.return_value.select.return_value.filter.return_value.execute.return_value = \
        MagicMock(data=[row])
    sb.table.return_value.delete.return_value.eq.return_value.execute.return_value = None

    with patch("app.onboarding.oauth._get_supabase", return_value=sb), \
         patch("app.retailers.create_retailer",
               return_value={"id": "aminas_minimart", "whatsapp": "+2348012345678",
                             "spreadsheet_id": "SHEET123"}) as mock_create, \
         patch("app.messaging.wuzapi_client.send_whatsapp") as mock_send, \
         patch("app.pipeline.run_digest") as mock_digest:
        from app.onboarding.oauth import finalize_with_sheet
        finalize_with_sheet(state_token="tok123", spreadsheet_id="SHEET123")
        created = mock_create.call_args[0][0]
        assert created["spreadsheet_id"] == "SHEET123"
        assert created["google_token"]["access_token"] == "acc"
        assert created["currency"] == "NGN"
        mock_send.assert_called()
        mock_digest.assert_called_once()


def test_finalize_with_sheet_rejects_when_tokens_missing():
    row = _fake_state_row()
    row["step"] = "awaiting_sheet_pick"
    # no google_token in data
    sb = MagicMock()
    sb.table.return_value.select.return_value.filter.return_value.execute.return_value = \
        MagicMock(data=[row])
    with patch("app.onboarding.oauth._get_supabase", return_value=sb):
        from app.onboarding.oauth import finalize_with_sheet
        with pytest.raises(ValueError, match="tokens missing"):
            finalize_with_sheet(state_token="tok123", spreadsheet_id="X")
