"""Tests for the retailer registry — YAML fallback when Supabase is unconfigured."""
from unittest.mock import patch


def _yaml_only_settings():
    """Settings with Supabase blank — forces YAML fallback path."""
    from pydantic_settings import SettingsConfigDict
    from app.settings import Settings

    class IsolatedSettings(Settings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")

    return IsolatedSettings(_env_file=None, supabase_url="", supabase_key="")  # type: ignore[call-arg]


def _patch_retailers_module():
    """Patch get_settings + clear cached supabase client inside app.retailers."""
    import app.retailers as m
    m._supabase_client = None
    return patch("app.retailers.get_settings", return_value=_yaml_only_settings())


def test_yaml_fallback_when_no_supabase():
    with _patch_retailers_module():
        from app.retailers import all_retailers
        retailers = all_retailers()
        assert len(retailers) >= 1
        assert retailers[0]["id"] == "demo"


def test_by_whatsapp_yaml_fallback():
    with _patch_retailers_module():
        from app.retailers import by_whatsapp
        r = by_whatsapp("+233242679643")
        assert r is not None
        assert r["id"] == "demo"


def test_by_whatsapp_returns_none_for_unknown():
    with _patch_retailers_module():
        from app.retailers import by_whatsapp
        assert by_whatsapp("+10000000000") is None


def test_digits_normalisation():
    with _patch_retailers_module():
        from app.retailers import by_whatsapp
        r = by_whatsapp("whatsapp:+233242679643")
        assert r is not None
