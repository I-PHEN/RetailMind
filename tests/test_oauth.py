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
