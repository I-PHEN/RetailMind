import os
import pytest


def _clear_cache():
    import app.retailers as m
    if hasattr(m, "_supabase_client"):
        m._supabase_client = None


def test_yaml_fallback_when_no_supabase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    # bust settings cache
    import app.settings as s
    s.get_settings.cache_clear()
    _clear_cache()

    from app.retailers import all_retailers
    retailers = all_retailers()
    # config/retailers.yaml has at least one retailer (demo)
    assert len(retailers) >= 1
    assert retailers[0]["id"] == "demo"


def test_by_whatsapp_yaml_fallback(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    import app.settings as s
    s.get_settings.cache_clear()
    _clear_cache()

    from app.retailers import by_whatsapp
    # The demo retailer has whatsapp_to: "whatsapp:+254700000000"
    r = by_whatsapp("+254700000000")
    assert r is not None
    assert r["id"] == "demo"


def test_by_whatsapp_returns_none_for_unknown(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    import app.settings as s
    s.get_settings.cache_clear()
    _clear_cache()

    from app.retailers import by_whatsapp
    assert by_whatsapp("+10000000000") is None


def test_digits_normalisation(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    import app.settings as s
    s.get_settings.cache_clear()
    _clear_cache()

    from app.retailers import by_whatsapp
    # whatsapp: prefix and leading + should still match
    r = by_whatsapp("whatsapp:+254700000000")
    assert r is not None
