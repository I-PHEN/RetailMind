"""Settings sanity tests — defaults are loaded and removed legacy fields stay removed."""
from pydantic_settings import SettingsConfigDict


def _fresh_settings_class():
    """Build a Settings subclass that ignores .env so tests don't depend on dev secrets."""
    from app.settings import Settings

    class IsolatedSettings(Settings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")

    return IsolatedSettings


def _fresh(env: dict | None = None):
    cls = _fresh_settings_class()
    return cls(_env_file=None, **(env or {}))  # type: ignore[call-arg]


def test_wuzapi_defaults():
    s = _fresh()
    assert s.wuzapi_api_url == "http://localhost:8080"
    assert s.wuzapi_token == ""


def test_supabase_defaults():
    s = _fresh()
    assert s.supabase_url == ""
    assert s.supabase_key == ""


def test_google_oauth_defaults():
    s = _fresh()
    assert s.google_oauth_client_id == ""
    assert s.google_oauth_client_secret == ""
    assert "callback" in s.google_oauth_redirect_uri
    assert s.google_api_key == ""


def test_legacy_fields_gone():
    """Twilio and Evolution settings were removed in earlier refactors."""
    s = _fresh()
    assert not hasattr(s, "twilio_account_sid")
    assert not hasattr(s, "evolution_api_url")
    assert not hasattr(s, "evolution_api_key")
    assert not hasattr(s, "evolution_instance")
