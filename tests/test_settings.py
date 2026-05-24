import importlib, os, sys

def _fresh_settings(env: dict):
    """Load Settings with a controlled env (no .env file)."""
    os.environ.update(env)
    # bust the lru_cache
    import app.settings as m
    m.get_settings.cache_clear()
    return m.Settings()


def test_evolution_defaults():
    s = _fresh_settings({})
    assert s.evolution_api_url == ""
    assert s.evolution_api_key == ""
    assert s.evolution_instance == "retailmind"


def test_supabase_defaults():
    s = _fresh_settings({})
    assert s.supabase_url == ""
    assert s.supabase_key == ""


def test_google_oauth_defaults():
    s = _fresh_settings({})
    assert s.google_oauth_client_id == ""
    assert s.google_oauth_client_secret == ""
    assert "callback" in s.google_oauth_redirect_uri


def test_twilio_fields_gone():
    s = _fresh_settings({})
    assert not hasattr(s, "twilio_account_sid")
