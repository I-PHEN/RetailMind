# Evolution API + Self-Serve Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Twilio with self-hosted Evolution API and add WhatsApp-first self-serve onboarding backed by Supabase, so retailers can sign themselves up with zero operator involvement.

**Architecture:** Evolution API runs as a Docker service on Render with a persistent disk for Baileys session storage. Inbound messages hit a rewritten webhook that routes unknown numbers to an onboarding FSM and known retailers to the existing agent. Supabase replaces `config/retailers.yaml` as the live retailer store, with a YAML fallback for local dev.

**Tech Stack:** Python 3.11+, FastAPI, `httpx` (Evolution API calls), `supabase-py`, `google-auth-oauthlib`, `google-auth-httplib2`, `google-api-python-client` (already used for Sheets)

**Spec:** `docs/superpowers/specs/2026-05-24-evolution-api-onboarding-design.md`

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `app/messaging/evolution_client.py` | **New** | Send WhatsApp messages via Evolution REST API |
| `app/messaging/twilio_client.py` | **Delete** | Replaced by evolution_client.py |
| `app/messaging/webhook.py` | **Rewrite** | Parse Evolution JSON webhook, route to onboarding or agent |
| `app/retailers.py` | **Rewrite** | Supabase reads/writes; YAML fallback when SUPABASE_URL unset |
| `app/settings.py` | **Extend** | Add Evolution, Supabase, Google OAuth env vars; remove Twilio |
| `app/pipeline.py` | **Patch** | Swap `send_whatsapp` import from twilio → evolution |
| `app/onboarding/__init__.py` | **New** | Package marker |
| `app/onboarding/name_parser.py` | **New** | Extract (owner_name, shop_name) from free-form text |
| `app/onboarding/oauth.py` | **New** | Build Google OAuth URL with state token; handle redirect |
| `app/onboarding/fsm.py` | **New** | Conversation state machine: greeting → name → oauth → done |
| `app/main.py` | **Extend** | Register `/auth/google/callback` route |
| `render.yaml` | **Extend** | Add Evolution Docker service + persistent disk; remove Twilio vars |
| `tests/test_evolution_client.py` | **New** | Unit tests for send/normalise logic |
| `tests/test_retailers.py` | **New** | Unit tests for YAML fallback + Supabase routing |
| `tests/test_name_parser.py` | **New** | Unit tests for name extraction |
| `tests/test_onboarding_fsm.py` | **New** | Unit tests for FSM state transitions |
| `tests/test_webhook.py` | **New** | Unit tests for Evolution webhook parsing + routing |

---

## Task 1: Settings — add new env vars, remove Twilio

**Files:**
- Modify: `app/settings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_settings.py -v
```
Expected: FAIL — `evolution_api_url` not found on Settings.

- [ ] **Step 3: Rewrite `app/settings.py`**

```python
"""Central settings — all secrets/config flow through here (pydantic-settings)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM (OpenAI-compatible; OpenRouter by default)
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-chat-v3-0324:free"

    # Evolution API (WhatsApp gateway)
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = "retailmind"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Google OAuth (for Sheets connection during onboarding)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Google Sheets service account (legacy / dev fallback)
    google_service_account_json: str = "./service-account.json"

    # App
    retailmind_config: str = "./config/retailers.yaml"
    app_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_settings.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add app/settings.py tests/test_settings.py
git commit -m "feat: settings — add Evolution/Supabase/OAuth vars, remove Twilio"
```

---

## Task 2: Evolution API client

**Files:**
- Create: `app/messaging/evolution_client.py`
- Delete: `app/messaging/twilio_client.py` (after this task)
- Create: `tests/test_evolution_client.py`

- [ ] **Step 1: Install httpx if not present**

```
pip install httpx
```

Add `httpx` to `requirements.txt` (check it isn't already there first — it may be a transitive dep).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_evolution_client.py`:

```python
from unittest.mock import MagicMock, patch
import pytest


def test_normalise_strips_whatsapp_prefix():
    from app.messaging.evolution_client import _normalise
    assert _normalise("whatsapp:+2348012345678") == "+2348012345678"
    assert _normalise("+2348012345678") == "+2348012345678"
    assert _normalise("2348012345678") == "+2348012345678"


def test_normalise_strips_jid_suffix():
    from app.messaging.evolution_client import _normalise
    assert _normalise("2348012345678@s.whatsapp.net") == "+2348012345678"


def test_send_whatsapp_calls_correct_endpoint():
    with patch("app.messaging.evolution_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"key": {"id": "abc"}})
        from app.messaging import evolution_client
        evolution_client._settings = MagicMock(
            evolution_api_url="http://evo",
            evolution_api_key="key123",
            evolution_instance="retailmind",
        )
        evolution_client.send_whatsapp("+2348012345678", "hello")
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "sendText/retailmind" in url
        payload = mock_post.call_args[1]["json"]
        assert payload["number"] == "+2348012345678"
        assert payload["text"] == "hello"


def test_send_whatsapp_raises_on_missing_config():
    from app.messaging import evolution_client
    evolution_client._settings = MagicMock(
        evolution_api_url="",
        evolution_api_key="",
        evolution_instance="retailmind",
    )
    with pytest.raises(RuntimeError, match="EVOLUTION"):
        evolution_client.send_whatsapp("+234...", "hi")
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_evolution_client.py -v
```
Expected: FAIL — `app.messaging.evolution_client` not found.

- [ ] **Step 4: Create `app/messaging/evolution_client.py`**

```python
"""Evolution API WhatsApp client. Replaces twilio_client.py."""
from __future__ import annotations

import httpx

from app.settings import get_settings

# Module-level settings ref — tests can swap this out
_settings = None


def _s():
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def _normalise(number: str) -> str:
    """Return E.164 (+digits) from any reasonable input format."""
    n = number.strip()
    # strip JID suffix
    if "@" in n:
        n = n.split("@")[0]
    # strip whatsapp: prefix
    if n.lower().startswith("whatsapp:"):
        n = n[len("whatsapp:"):]
    # ensure leading +
    if not n.startswith("+"):
        n = "+" + n
    return n


def send_whatsapp(to: str, body: str) -> None:
    """Send a text message to `to` via Evolution API."""
    s = _s()
    if not s.evolution_api_url or not s.evolution_api_key:
        raise RuntimeError("EVOLUTION_API_URL / EVOLUTION_API_KEY not set in env")

    url = f"{s.evolution_api_url.rstrip('/')}/message/sendText/{s.evolution_instance}"
    headers = {"apikey": s.evolution_api_key, "Content-Type": "application/json"}
    payload = {"number": _normalise(to), "text": body}
    resp = httpx.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()


def send_whatsapp_link(to: str, url: str, title: str, body: str) -> None:
    """Send a link preview card — used for the Google OAuth URL during onboarding."""
    s = _s()
    if not s.evolution_api_url or not s.evolution_api_key:
        raise RuntimeError("EVOLUTION_API_URL / EVOLUTION_API_KEY not set in env")

    endpoint = f"{s.evolution_api_url.rstrip('/')}/message/sendLink/{s.evolution_instance}"
    headers = {"apikey": s.evolution_api_key, "Content-Type": "application/json"}
    payload = {
        "number": _normalise(to),
        "linkPreview": {
            "url": url,
            "title": title,
            "description": body,
        },
    }
    resp = httpx.post(endpoint, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_evolution_client.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Delete `app/messaging/twilio_client.py`**

```
git rm app/messaging/twilio_client.py
```

- [ ] **Step 7: Commit**

```
git add app/messaging/evolution_client.py tests/test_evolution_client.py
git commit -m "feat: Evolution API client — send_whatsapp + send_whatsapp_link; rm Twilio"
```

---

## Task 3: Patch `pipeline.py` — swap Twilio import

**Files:**
- Modify: `app/pipeline.py:10,25`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_import.py`:

```python
def test_pipeline_does_not_import_twilio():
    import ast, pathlib
    src = pathlib.Path("app/pipeline.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "twilio" not in module.lower(), "pipeline.py still imports twilio"
            for n in names:
                assert "twilio" not in n.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_import.py -v
```
Expected: FAIL — twilio import found.

- [ ] **Step 3: Edit `app/pipeline.py`**

Change line 10 and line 25:

```python
"""Shared pipeline: load → analyze → narrate → (optionally) send."""
from __future__ import annotations

from typing import Any

from app.ai.narrator import narrate
from app.analytics.engine import build_bundle
from app.connectors import load_source
from app.messaging.evolution_client import send_whatsapp


def build_for(retailer: dict[str, Any]) -> dict[str, Any]:
    df = load_source(retailer["source"])
    return build_bundle(df, {"currency": retailer.get("currency", ""), "retailer": retailer})


def run_digest(retailer: dict[str, Any], mode: str = "digest", send: bool = True) -> dict[str, Any]:
    bundle = build_for(retailer)
    message = narrate(bundle, retailer, mode=mode)
    if send:
        send_whatsapp(retailer["whatsapp"], message)
    return {
        "retailer": retailer["id"],
        "mode": mode,
        "message": message,
        "has_high_severity": bundle["has_high_severity"],
        "insight_count": len(bundle["insights"]),
        "insight_names": [i["name"] for i in bundle["insights"]],
    }
```

Note: `retailer["whatsapp_to"]` → `retailer["whatsapp"]` because Supabase schema uses `whatsapp` (not `whatsapp_to`). Also removed `twilio_sid` from the return dict.

- [ ] **Step 4: Run tests**

```
pytest tests/test_pipeline_import.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```
git add app/pipeline.py tests/test_pipeline_import.py
git commit -m "fix: pipeline — swap Twilio → Evolution client, retailer.whatsapp field"
```

---

## Task 3b: Patch connectors — support OAuth token alongside service account

**Context:** `app/connectors/google_sheets.py` currently uses a service-account JSON file.
Supabase retailers have a flat `google_token` (OAuth access/refresh token) and `spreadsheet_id`
at the top level — no nested `source` dict. `pipeline.build_for` must handle both shapes.

**Files:**
- Modify: `app/connectors/google_sheets.py`
- Modify: `app/pipeline.py`
- Create: `tests/test_connectors_build_for.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_connectors_build_for.py`:

```python
from unittest.mock import patch, MagicMock
import pandas as pd


def _fake_df():
    return pd.DataFrame({
        "date": ["2024-01-01"],
        "product": ["Rice"],
        "quantity": [10],
        "unit_price": [5.0],
        "revenue": [50.0],
    })


def test_build_for_yaml_shape():
    """YAML retailer: has nested source dict → uses service account path."""
    retailer = {
        "id": "demo",
        "currency": "KES",
        "source": {"type": "csv", "path": "data/sample_sales.csv"},
    }
    with patch("app.pipeline.load_source", return_value=_fake_df()) as mock_load, \
         patch("app.pipeline.build_bundle", return_value={"insights": [], "has_high_severity": False}):
        from app.pipeline import build_for
        build_for(retailer)
        mock_load.assert_called_once_with({"type": "csv", "path": "data/sample_sales.csv"})


def test_build_for_supabase_shape():
    """Supabase retailer: flat spreadsheet_id + google_token → constructs source dict."""
    retailer = {
        "id": "amina",
        "currency": "NGN",
        "spreadsheet_id": "SHEET_ID_123",
        "google_token": {"access_token": "tok", "refresh_token": "ref"},
        # no 'source' key
    }
    with patch("app.pipeline.load_source", return_value=_fake_df()) as mock_load, \
         patch("app.pipeline.build_bundle", return_value={"insights": [], "has_high_severity": False}):
        from app.pipeline import build_for
        build_for(retailer)
        call_arg = mock_load.call_args[0][0]
        assert call_arg["type"] == "google_sheet"
        assert call_arg["spreadsheet_id"] == "SHEET_ID_123"
        assert call_arg["google_token"] == {"access_token": "tok", "refresh_token": "ref"}
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_connectors_build_for.py -v
```
Expected: FAIL — `build_for` doesn't handle Supabase shape yet.

- [ ] **Step 3: Update `app/pipeline.py` — handle both retailer shapes**

```python
"""Shared pipeline: load → analyze → narrate → (optionally) send."""
from __future__ import annotations

from typing import Any

from app.ai.narrator import narrate
from app.analytics.engine import build_bundle
from app.connectors import load_source
from app.messaging.evolution_client import send_whatsapp


def _source_from_retailer(retailer: dict[str, Any]) -> dict[str, Any]:
    """Build a source config dict from either a YAML retailer or a Supabase retailer."""
    if "source" in retailer:
        return retailer["source"]  # YAML shape — already a source dict
    # Supabase shape — flat fields
    return {
        "type": "google_sheet",
        "spreadsheet_id": retailer["spreadsheet_id"],
        "google_token": retailer.get("google_token"),
    }


def build_for(retailer: dict[str, Any]) -> dict[str, Any]:
    df = load_source(_source_from_retailer(retailer))
    return build_bundle(df, {"currency": retailer.get("currency", ""), "retailer": retailer})


def run_digest(retailer: dict[str, Any], mode: str = "digest", send: bool = True) -> dict[str, Any]:
    bundle = build_for(retailer)
    message = narrate(bundle, retailer, mode=mode)
    if send:
        send_whatsapp(retailer["whatsapp"], message)
    return {
        "retailer": retailer["id"],
        "mode": mode,
        "message": message,
        "has_high_severity": bundle["has_high_severity"],
        "insight_count": len(bundle["insights"]),
        "insight_names": [i["name"] for i in bundle["insights"]],
    }
```

- [ ] **Step 4: Update `app/connectors/google_sheets.py` — accept OAuth token**

```python
"""Google Sheets connector — service account (dev) or OAuth token (production)."""
from __future__ import annotations

import pandas as pd

from app.schema import normalize
from app.settings import get_settings

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def load_google_sheet(
    spreadsheet_id: str,
    worksheet: str | None = None,
    google_token: dict | None = None,
) -> pd.DataFrame:
    import gspread

    if google_token and google_token.get("access_token"):
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=google_token["access_token"],
            refresh_token=google_token.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=google_token.get("client_id"),
            client_secret=google_token.get("client_secret"),
        )
    else:
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            get_settings().google_service_account_json, scopes=_SCOPES
        )

    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet(worksheet) if worksheet else sh.sheet1
    raw = pd.DataFrame(ws.get_all_records())
    return normalize(raw)
```

- [ ] **Step 5: Update `app/connectors/__init__.py` — pass google_token through**

```python
"""Data connectors — each returns a canonical-schema DataFrame via app.schema.normalize."""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.connectors.csv_loader import load_csv
from app.connectors.google_sheets import load_google_sheet


def load_source(source: dict[str, Any]) -> pd.DataFrame:
    """Dispatch on a source config dict (from pipeline._source_from_retailer)."""
    stype = source.get("type", "csv")
    if stype == "csv":
        return load_csv(source["path"])
    if stype == "google_sheet":
        return load_google_sheet(
            source["spreadsheet_id"],
            source.get("worksheet"),
            source.get("google_token"),
        )
    raise ValueError(f"Unknown source type: {stype!r}")
```

- [ ] **Step 6: Run tests**

```
pytest tests/test_connectors_build_for.py tests/test_pipeline_import.py -v
```
Expected: all pass.

- [ ] **Step 7: Run Phase 1–2 smoke-tests to confirm nothing broke**

```
python -m app.connectors.csv_loader data/sample_sales.csv
python -m app.analytics.engine data/sample_sales.csv
```
Expected: both print output without error.

- [ ] **Step 8: Commit**

```
git add app/pipeline.py app/connectors/__init__.py app/connectors/google_sheets.py tests/test_connectors_build_for.py
git commit -m "feat: connectors — support OAuth token for Sheets; pipeline handles Supabase retailer shape"
```

---

## Task 4: Supabase retailer store

**Files:**
- Rewrite: `app/retailers.py`
- Create: `tests/test_retailers.py`

- [ ] **Step 1: Install supabase-py**

```
pip install supabase
```

Add `supabase` to `requirements.txt`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_retailers.py`:

```python
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
    # The demo retailer has whatsapp: +233242679643
    r = by_whatsapp("+233242679643")
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
    r = by_whatsapp("whatsapp:+233242679643")
    assert r is not None
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_retailers.py -v
```
Expected: FAIL — `_supabase_client` attribute not found / function signatures wrong.

- [ ] **Step 4: Rewrite `app/retailers.py`**

```python
"""Retailer registry — Supabase in production, YAML fallback in dev."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import yaml

from app.settings import get_settings

# Module-level client — None until first use
_supabase_client = None


def _digits(num: str) -> str:
    return re.sub(r"\D", "", num)


def _get_supabase():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    s = get_settings()
    if not s.supabase_url or not s.supabase_key:
        return None
    from supabase import create_client
    _supabase_client = create_client(s.supabase_url, s.supabase_key)
    return _supabase_client


# ---------- YAML fallback (dev / local smoke-tests) ----------

@lru_cache
def _load_yaml() -> list[dict[str, Any]]:
    with open(get_settings().retailmind_config, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    rows = data.get("retailers", [])
    # Normalise YAML rows to match the Supabase column names
    normalised = []
    for r in rows:
        row = dict(r)
        # YAML uses whatsapp_to; internal interface uses whatsapp
        if "whatsapp_to" in row and "whatsapp" not in row:
            row["whatsapp"] = row.pop("whatsapp_to")
        # strip whatsapp: prefix
        if row.get("whatsapp", "").startswith("whatsapp:"):
            row["whatsapp"] = row["whatsapp"][len("whatsapp:"):]
        normalised.append(row)
    return normalised


# ---------- Public interface ----------

def all_retailers() -> list[dict[str, Any]]:
    """Return all active retailers. Scheduler calls this."""
    sb = _get_supabase()
    if sb is None:
        return _load_yaml()
    resp = sb.table("retailers").select("*").eq("status", "active").execute()
    return resp.data


def get_retailer(retailer_id: str) -> dict[str, Any] | None:
    sb = _get_supabase()
    if sb is None:
        return next((r for r in _load_yaml() if r.get("id") == retailer_id), None)
    resp = sb.table("retailers").select("*").eq("id", retailer_id).execute()
    return resp.data[0] if resp.data else None


def by_whatsapp(number: str) -> dict[str, Any] | None:
    """Match an inbound number (any format) to a retailer."""
    target = _digits(number)
    sb = _get_supabase()
    if sb is None:
        return next(
            (r for r in _load_yaml() if _digits(r.get("whatsapp", "")) == target),
            None,
        )
    resp = sb.table("retailers").select("*").execute()
    return next(
        (r for r in resp.data if _digits(r.get("whatsapp", "")) == target),
        None,
    )


def create_retailer(data: dict[str, Any]) -> dict[str, Any]:
    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured — cannot create retailer in dev mode")
    resp = sb.table("retailers").insert(data).execute()
    return resp.data[0]


def update_retailer(retailer_id: str, data: dict[str, Any]) -> dict[str, Any]:
    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured — cannot update retailer in dev mode")
    resp = sb.table("retailers").update(data).eq("id", retailer_id).execute()
    return resp.data[0]
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_retailers.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```
git add app/retailers.py tests/test_retailers.py requirements.txt
git commit -m "feat: retailers — Supabase store with YAML fallback for dev"
```

---

## Task 5: Name parser

**Files:**
- Create: `app/onboarding/__init__.py`
- Create: `app/onboarding/name_parser.py`
- Create: `tests/test_name_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_name_parser.py`:

```python
from app.onboarding.name_parser import parse_name


def test_standard_intro():
    owner, shop = parse_name("I'm Amina, Amina's Mini-Mart")
    assert owner == "Amina"
    assert "Mini-Mart" in shop


def test_my_name_is_pattern():
    owner, shop = parse_name("My name is John, John's Pharmacy")
    assert owner == "John"
    assert "Pharmacy" in shop


def test_name_only_no_shop():
    owner, shop = parse_name("Amina")
    assert owner == "Amina"
    assert shop == "Amina's Shop"  # default fallback


def test_name_and_shop_no_intro():
    owner, shop = parse_name("Kofi, Kofi Mart")
    assert owner == "Kofi"
    assert "Mart" in shop


def test_strips_punctuation():
    owner, shop = parse_name("  Fatima!  Fatima Stores  ")
    assert owner == "Fatima"
    assert "Stores" in shop
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_name_parser.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Create `app/onboarding/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `app/onboarding/name_parser.py`**

```python
"""Extract (owner_name, shop_name) from a free-form introduction message."""
from __future__ import annotations

import re


def parse_name(text: str) -> tuple[str, str]:
    """Return (owner_name, shop_name).

    Handles patterns like:
      "I'm Amina, Amina's Mini-Mart"
      "My name is John, John's Pharmacy"
      "Kofi, Kofi Mart"
      "Amina"   → shop defaults to "Amina's Shop"
    """
    text = text.strip().strip("!.?")

    # Strip intro phrases
    intro_re = re.compile(
        r"^(i(?:'m| am)|my name is)\s+", re.IGNORECASE
    )
    text = intro_re.sub("", text).strip()

    # Split on first comma or newline to separate name from shop
    parts = re.split(r"[,\n]+", text, maxsplit=1)
    owner = parts[0].strip().strip("!.?")
    # Take only the first word(s) that look like a name (capitalised, no spaces > 3 words)
    name_words = owner.split()
    owner = " ".join(name_words[:2])  # at most first + last name

    if len(parts) > 1:
        shop = parts[1].strip().strip("!.?")
    else:
        shop = f"{owner}'s Shop"

    return owner, shop or f"{owner}'s Shop"
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_name_parser.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```
git add app/onboarding/__init__.py app/onboarding/name_parser.py tests/test_name_parser.py
git commit -m "feat: onboarding name_parser — extract owner/shop name from free-form text"
```

---

## Task 6: Google OAuth helper

**Files:**
- Create: `app/onboarding/oauth.py`
- Create: `tests/test_oauth.py`

Dependencies: `google-auth-oauthlib` (check `requirements.txt` — likely already present for Sheets).

- [ ] **Step 1: Verify / add google-auth-oauthlib**

```
pip show google-auth-oauthlib
```

If not installed: `pip install google-auth-oauthlib` and add to `requirements.txt`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_oauth.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_oauth.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 4: Create `app/onboarding/oauth.py`**

```python
"""Google OAuth helpers for the Sheets connection step of onboarding."""
from __future__ import annotations

import secrets
from typing import Any

from google_auth_oauthlib.flow import Flow

from app.settings import get_settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def build_oauth_url(whatsapp: str) -> tuple[str, str]:
    """Return (authorization_url, state_token).

    state_token is a 32-char hex string the caller must store in onboarding_state.data
    so the redirect handler can recover which WhatsApp number is completing OAuth.
    """
    s = get_settings()
    state_token = secrets.token_hex(16)  # 32 hex chars

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [s.google_oauth_redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=s.google_oauth_redirect_uri,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state_token,
        prompt="consent",  # force refresh_token to be returned
    )
    return auth_url, state_token


def exchange_code(code: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens. Returns a dict with token data."""
    s = get_settings()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [s.google_oauth_redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=s.google_oauth_redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
        "client_id": s.google_oauth_client_id,
        "client_secret": s.google_oauth_client_secret,
    }
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_oauth.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```
git add app/onboarding/oauth.py tests/test_oauth.py
git commit -m "feat: onboarding oauth — build Google OAuth URL + exchange code for tokens"
```

---

## Task 7: Onboarding FSM

**Files:**
- Create: `app/onboarding/fsm.py`
- Create: `tests/test_onboarding_fsm.py`

This is the conversation state machine. It reads/writes `onboarding_state` in Supabase. For tests we mock the Supabase client and the Evolution send functions.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_onboarding_fsm.py`:

```python
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
         patch("app.onboarding.fsm.send_whatsapp_link") as mock_link, \
         patch("app.onboarding.fsm.build_oauth_url", return_value=("https://oauth.url", "tok123")):
        from app.onboarding import fsm
        import importlib; importlib.reload(fsm)
        fsm.handle("+2348012345678", "I'm Amina, Amina's Mini-Mart")
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
        from app.onboarding import fsm
        import importlib; importlib.reload(fsm)
        fsm.handle("+2348012345678", "hello?")
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "link" in msg.lower() or "connect" in msg.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_onboarding_fsm.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Create `app/onboarding/fsm.py`**

```python
"""Onboarding conversation state machine.

States: greeting → awaiting_name → awaiting_oauth → (done, handled by oauth callback)
Reads/writes onboarding_state table in Supabase.
"""
from __future__ import annotations

import logging
from typing import Any

from app.messaging.evolution_client import send_whatsapp, send_whatsapp_link
from app.onboarding.name_parser import parse_name
from app.onboarding.oauth import build_oauth_url
from app.settings import get_settings

log = logging.getLogger("retailmind.onboarding")

_TIMEZONE_MAP = {
    "+234": "Africa/Lagos",
    "+254": "Africa/Nairobi",
    "+233": "Africa/Accra",
    "+256": "Africa/Kampala",
    "+255": "Africa/Dar_es_Salaam",
    "+27":  "Africa/Johannesburg",
    "+260": "Africa/Lusaka",
    "+263": "Africa/Harare",
    "+225": "Africa/Abidjan",
    "+221": "Africa/Dakar",
}

_DEFAULT_TZ = "Africa/Lagos"


def _detect_timezone(whatsapp: str) -> str:
    for prefix, tz in _TIMEZONE_MAP.items():
        if whatsapp.startswith(prefix):
            return tz
    return _DEFAULT_TZ


# --- Supabase access (module-level so tests can patch) ---

_supabase_client = None


def _get_supabase():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    s = get_settings()
    if not s.supabase_url or not s.supabase_key:
        return None
    from supabase import create_client
    _supabase_client = create_client(s.supabase_url, s.supabase_key)
    return _supabase_client


def _get_state(whatsapp: str) -> dict[str, Any] | None:
    sb = _get_supabase()
    if sb is None:
        return None
    resp = sb.table("onboarding_state").select("*").eq("whatsapp", whatsapp).execute()
    return resp.data[0] if resp.data else None


def _set_state(whatsapp: str, step: str, data: dict[str, Any]) -> None:
    sb = _get_supabase()
    if sb is None:
        return
    sb.table("onboarding_state").upsert({
        "whatsapp": whatsapp,
        "step": step,
        "data": data,
    }).execute()


def handle(whatsapp: str, text: str) -> None:
    """Process one inbound message from an unknown (onboarding) number."""
    state = _get_state(whatsapp)

    if state is None:
        # First contact — send greeting and record state
        _set_state(whatsapp, "awaiting_name", {})
        send_whatsapp(
            whatsapp,
            "Hi 👋 I'm RetailMind, your AI business partner.\n\n"
            "What's your name and what do you call your shop?",
        )
        return

    step = state.get("step", "greeting")
    data = state.get("data", {})

    if step == "awaiting_name":
        owner, shop = parse_name(text)
        auth_url, state_token = build_oauth_url(whatsapp)
        _set_state(whatsapp, "awaiting_oauth", {
            **data,
            "name": owner,
            "shop_name": shop,
            "oauth_state_token": state_token,
            "timezone": _detect_timezone(whatsapp),
        })
        send_whatsapp(whatsapp, f"Nice to meet you {owner}! 🛒\n\nNow I need to see your sales data. Tap below to connect your Google Sheet:")
        send_whatsapp_link(
            whatsapp,
            auth_url,
            "Connect Google Sheet",
            "Tap to authorise RetailMind to read your sales sheet",
        )
        return

    if step == "awaiting_oauth":
        # They messaged again before completing OAuth — remind them
        send_whatsapp(
            whatsapp,
            "Still waiting for you to connect your Google Sheet 👆\n"
            "Tap the link above when you're ready!",
        )
        return

    log.warning("onboarding handle called for %s in unknown step %s", whatsapp, step)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_onboarding_fsm.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add app/onboarding/fsm.py tests/test_onboarding_fsm.py
git commit -m "feat: onboarding FSM — greeting/name/oauth states with Supabase persistence"
```

---

## Task 8: Rewrite webhook handler

**Files:**
- Rewrite: `app/messaging/webhook.py`
- Create: `tests/test_webhook.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_webhook.py`:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def _make_app():
    from app.messaging.webhook import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


def _evolution_payload(jid: str, text: str) -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": jid, "fromMe": False},
            "message": {"conversation": text},
        },
    }


def test_unknown_number_routes_to_onboarding():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp", return_value=None) as mock_lookup, \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post(
            "/webhook/whatsapp",
            json=_evolution_payload("2348012345678@s.whatsapp.net", "Hi"),
        )
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+2348012345678", "Hi")


def test_known_number_routes_to_agent():
    client = TestClient(_make_app())
    retailer = {"id": "demo", "whatsapp": "+2348012345678"}
    with patch("app.messaging.webhook.by_whatsapp", return_value=retailer), \
         patch("app.messaging.webhook.answer", return_value="reply text") as mock_answer, \
         patch("app.messaging.webhook.send_whatsapp") as mock_send:
        resp = client.post(
            "/webhook/whatsapp",
            json=_evolution_payload("2348012345678@s.whatsapp.net", "How were sales?"),
        )
        assert resp.status_code == 200
        mock_answer.assert_called_once()
        mock_send.assert_called()


def test_ignores_own_messages():
    """Messages with fromMe=True (bot's own sends) must not loop."""
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post(
            "/webhook/whatsapp",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {"remoteJid": "234@s.whatsapp.net", "fromMe": True},
                    "message": {"conversation": "bot echo"},
                },
            },
        )
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_ignores_non_message_events():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp") as mock_lookup:
        resp = client.post(
            "/webhook/whatsapp",
            json={"event": "connection.update", "data": {}},
        )
        assert resp.status_code == 200
        mock_lookup.assert_not_called()


def test_extended_text_message_extracted():
    client = TestClient(_make_app())
    with patch("app.messaging.webhook.by_whatsapp", return_value=None), \
         patch("app.messaging.webhook.onboarding_handle") as mock_onboard:
        resp = client.post(
            "/webhook/whatsapp",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {"remoteJid": "234@s.whatsapp.net", "fromMe": False},
                    "message": {
                        "extendedTextMessage": {"text": "quoted reply text"}
                    },
                },
            },
        )
        assert resp.status_code == 200
        mock_onboard.assert_called_once_with("+234", "quoted reply text")
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_webhook.py -v
```
Expected: FAIL — old Twilio webhook shape.

- [ ] **Step 3: Rewrite `app/messaging/webhook.py`**

```python
"""Evolution API inbound WhatsApp webhook → route to onboarding or agent."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.ai.agent import answer
from app.messaging.evolution_client import send_whatsapp
from app.onboarding.fsm import handle as onboarding_handle
from app.retailers import by_whatsapp

log = logging.getLogger("retailmind.webhook")
router = APIRouter()


def _extract(payload: dict) -> tuple[str, str] | None:
    """Return (normalised_number, message_text) or None if not a real inbound message."""
    if payload.get("event") != "messages.upsert":
        return None
    data = payload.get("data", {})
    key = data.get("key", {})
    if key.get("fromMe"):
        return None  # ignore echo of bot's own sends
    jid = key.get("remoteJid", "")
    if not jid:
        return None
    # normalise JID → E.164
    number = "+" + jid.split("@")[0].lstrip("+")
    msg = data.get("message", {})
    text = (
        msg.get("conversation")
        or msg.get("extendedTextMessage", {}).get("text")
        or ""
    ).strip()
    if not text:
        return None
    return number, text


@router.post("/webhook/whatsapp")
async def whatsapp_inbound(request: Request) -> JSONResponse:
    """Evolution posts JSON; we ack immediately and handle out-of-band."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({})

    extracted = _extract(payload)
    if extracted is None:
        return JSONResponse({})

    number, text = extracted
    retailer = by_whatsapp(number)

    if retailer is None:
        try:
            onboarding_handle(number, text)
        except Exception:
            log.exception("onboarding failed for %s", number)
        return JSONResponse({})

    # Known retailer — ack then answer
    try:
        send_whatsapp(number, "📊 On it — pulling your numbers…")
    except Exception:
        log.warning("ack failed for %s", number)

    try:
        reply = answer(retailer, number, text)
        send_whatsapp(number, reply)
    except Exception:
        log.exception("agent failed for %s", retailer.get("id"))
        try:
            send_whatsapp(number, "Sorry, I hit a snag. Try again in a moment?")
        except Exception:
            pass

    return JSONResponse({})
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_webhook.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add app/messaging/webhook.py tests/test_webhook.py
git commit -m "feat: webhook — rewrite for Evolution JSON format, route onboarding vs agent"
```

---

## Task 9: OAuth callback route + onboarding completion

**Files:**
- Modify: `app/main.py`
- Modify: `app/onboarding/oauth.py` (add `complete_onboarding`)

The OAuth callback is the moment a retailer finishes connecting their Google Sheet. It must:
1. Exchange the code for tokens
2. Look up the WhatsApp number from the state token
3. Create the retailer in Supabase
4. Send the confirmation WhatsApp + first digest

- [ ] **Step 1: Write the failing test**

Add to `tests/test_oauth.py`:

```python
def test_complete_onboarding_creates_retailer_and_sends_digest():
    from unittest.mock import patch, MagicMock

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
         patch("app.onboarding.oauth.create_retailer", return_value={"id": "amina_minimart", "whatsapp": "+2348012345678"}), \
         patch("app.onboarding.oauth.send_whatsapp") as mock_send, \
         patch("app.onboarding.oauth.run_digest") as mock_digest:
        from app.onboarding.oauth import complete_onboarding
        complete_onboarding(code="authcode123", state_token="tok123")
        mock_send.assert_called()
        mock_digest.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_oauth.py::test_complete_onboarding_creates_retailer_and_sends_digest -v
```
Expected: FAIL — `complete_onboarding` not defined.

- [ ] **Step 3: Add `complete_onboarding` to `app/onboarding/oauth.py`**

Append to the existing file:

```python
import re as _re
import logging as _logging

_log = _logging.getLogger("retailmind.onboarding.oauth")

_supabase_client = None


def _get_supabase():
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    s = get_settings()
    if not s.supabase_url or not s.supabase_key:
        return None
    from supabase import create_client
    _supabase_client = create_client(s.supabase_url, s.supabase_key)
    return _supabase_client


def complete_onboarding(code: str, state_token: str) -> str:
    """Exchange OAuth code, create retailer, send confirmation + first digest.

    Returns the retailer's WhatsApp number (for the HTTP response).
    Raises ValueError if the state_token is not found.
    """
    from app.retailers import create_retailer
    from app.messaging.evolution_client import send_whatsapp
    from app.pipeline import run_digest

    tokens = exchange_code(code)

    sb = _get_supabase()
    if sb is None:
        raise RuntimeError("Supabase not configured")

    # Recover the WhatsApp number from the state token
    resp = (
        sb.table("onboarding_state")
        .select("*")
        .filter("data->>oauth_state_token", "eq", state_token)
        .execute()
    )
    if not resp.data:
        raise ValueError(f"Unknown state token: {state_token}")

    row = resp.data[0]
    whatsapp = row["whatsapp"]
    data = row["data"]
    name = data.get("name", "")
    shop_name = data.get("shop_name", f"{name}'s Shop")
    timezone = data.get("timezone", "Africa/Lagos")

    # Build retailer id from shop name
    retailer_id = _re.sub(r"[^\w]", "_", shop_name.lower()).strip("_")[:30]

    retailer = create_retailer({
        "id": retailer_id,
        "name": shop_name,
        "whatsapp": whatsapp,
        "currency": "USD",
        "timezone": timezone,
        "digest_time": "08:00",
        "google_token": tokens,
        "status": "active",
    })

    # Clean up onboarding state
    sb.table("onboarding_state").delete().eq("whatsapp", whatsapp).execute()

    send_whatsapp(
        whatsapp,
        f"Perfect! You're all set {name} 🎉\n"
        f"I'll send you a summary every morning at 8am ⏰\n"
        f"First one coming now 👇",
    )

    try:
        run_digest(retailer, mode="digest", send=True)
    except Exception:
        _log.exception("first digest failed for %s", retailer_id)

    return whatsapp
```

- [ ] **Step 4: Run test**

```
pytest tests/test_oauth.py -v
```
Expected: all passed.

- [ ] **Step 5: Add OAuth callback route to `app/main.py`**

Add the import and route:

```python
"""RetailMind FastAPI app: health, on-demand trigger, inbound webhook, scheduler."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.messaging.webhook import router as webhook_router
from app.pipeline import run_digest
from app.retailers import all_retailers, get_retailer
from app.scheduler.jobs import run_poll, start_scheduler

logging.basicConfig(level=logging.INFO,
                     format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("retailmind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = start_scheduler()
    try:
        yield
    finally:
        sched.shutdown(wait=False)


app = FastAPI(title="RetailMind", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "retailers": [r["id"] for r in all_retailers()]}


@app.get("/auth/google/callback", response_class=HTMLResponse)
def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> HTMLResponse:
    """Google redirects here after the retailer authorises access to their Sheet."""
    from app.onboarding.oauth import complete_onboarding
    try:
        complete_onboarding(code=code, state_token=state)
    except Exception:
        log.exception("OAuth callback failed")
        return HTMLResponse(
            "<html><body><h2>Something went wrong.</h2>"
            "<p>Please go back to WhatsApp and try again.</p></body></html>",
            status_code=500,
        )
    return HTMLResponse(
        "<html><body>"
        "<h2>You're connected! ✅</h2>"
        "<p>Go back to WhatsApp — RetailMind is sending your first summary now.</p>"
        "</body></html>"
    )


@app.post("/trigger/{retailer_id}")
def trigger(retailer_id: str, mode: str = "digest", send: bool = True) -> dict:
    retailer = get_retailer(retailer_id)
    if not retailer:
        raise HTTPException(404, f"unknown retailer {retailer_id!r}")
    try:
        return run_digest(retailer, mode=mode, send=send)
    except Exception as exc:
        log.exception("trigger failed for %s", retailer_id)
        raise HTTPException(500, str(exc))


@app.post("/poll/{retailer_id}")
def poll(retailer_id: str) -> dict:
    retailer = get_retailer(retailer_id)
    if not retailer:
        raise HTTPException(404, f"unknown retailer {retailer_id!r}")
    try:
        return run_poll(retailer)
    except Exception as exc:
        log.exception("poll failed for %s", retailer_id)
        raise HTTPException(500, str(exc))
```

- [ ] **Step 6: Run all tests**

```
pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 7: Commit**

```
git add app/onboarding/oauth.py app/main.py tests/test_oauth.py
git commit -m "feat: OAuth callback — complete onboarding, create retailer, send first digest"
```

---

## Task 10: Supabase schema migration

**Files:**
- Create: `db/migrations/001_initial_schema.sql`

This SQL is run once in the Supabase dashboard (SQL editor). It is not auto-applied — document it clearly.

- [ ] **Step 1: Create the migration file**

Create `db/migrations/001_initial_schema.sql`:

```sql
-- RetailMind initial schema
-- Run once in Supabase SQL editor: https://app.supabase.com → SQL Editor

create table if not exists retailers (
  id              text primary key,
  name            text not null,
  whatsapp        text not null unique,
  currency        text not null default 'USD',
  timezone        text not null default 'Africa/Lagos',
  digest_time     text not null default '08:00',
  spreadsheet_id  text,
  google_token    jsonb,
  status          text not null default 'onboarding'
    check (status in ('onboarding', 'active', 'paused')),
  created_at      timestamptz default now()
);

create table if not exists onboarding_state (
  whatsapp    text primary key,
  step        text not null
    check (step in ('awaiting_name', 'awaiting_oauth', 'done')),
  data        jsonb default '{}',
  updated_at  timestamptz default now()
);

-- auto-update updated_at on onboarding_state
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger onboarding_state_updated_at
  before update on onboarding_state
  for each row execute procedure set_updated_at();
```

- [ ] **Step 2: Commit**

```
git add db/migrations/001_initial_schema.sql
git commit -m "chore: Supabase schema — retailers + onboarding_state tables"
```

---

## Task 11: Update `render.yaml` — add Evolution API service

**Files:**
- Modify: `render.yaml`

- [ ] **Step 1: Replace `render.yaml` with the updated blueprint**

```yaml
# Render Blueprint for RetailMind.
#
# After deploying:
#   1. In the Evolution service dashboard → scan QR with your WhatsApp number.
#   2. In the RetailMind service → add secret env vars (see below).
#   3. Point Evolution webhook at: https://<retailmind-service>.onrender.com/webhook/whatsapp
#   4. Add Google OAuth redirect URI in Google Cloud Console.
#
# Secret env vars to set manually in Render dashboard (never in git):
#   RetailMind service:
#     LLM_API_KEY, EVOLUTION_API_KEY, SUPABASE_URL, SUPABASE_KEY,
#     GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, GOOGLE_OAUTH_REDIRECT_URI,
#     APP_BASE_URL (= https://<retailmind>.onrender.com)
#   Evolution service:
#     AUTHENTICATION_API_KEY  (same value as EVOLUTION_API_KEY above)

services:
  - type: web
    name: retailmind
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: PYTHON_VERSION
        value: "3.12.7"
      - key: LLM_BASE_URL
        value: https://openrouter.ai/api/v1
      - key: LLM_MODEL
        value: qwen/qwen3-next-80b-a3b-instruct:free
      - key: EVOLUTION_INSTANCE
        value: retailmind
      - key: LLM_API_KEY
        sync: false
      - key: EVOLUTION_API_URL
        sync: false
      - key: EVOLUTION_API_KEY
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_KEY
        sync: false
      - key: GOOGLE_OAUTH_CLIENT_ID
        sync: false
      - key: GOOGLE_OAUTH_CLIENT_SECRET
        sync: false
      - key: GOOGLE_OAUTH_REDIRECT_URI
        sync: false
      - key: APP_BASE_URL
        sync: false

  - type: web
    name: retailmind-evolution
    runtime: docker
    plan: starter          # needs always-on + persistent disk
    dockerfilePath: ./evolution.Dockerfile
    healthCheckPath: /
    disk:
      name: evolution-sessions
      mountPath: /evolution/instances
      sizeGB: 1
    envVars:
      - key: AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES
        value: "true"
      - key: AUTHENTICATION_TYPE
        value: apikey
      - key: AUTHENTICATION_API_KEY
        sync: false        # set same value as EVOLUTION_API_KEY in retailmind service
      - key: WEBHOOK_GLOBAL_URL
        sync: false        # set to https://<retailmind>.onrender.com/webhook/whatsapp
      - key: WEBHOOK_GLOBAL_ENABLED
        value: "true"
      - key: WEBHOOK_EVENTS_MESSAGES_UPSERT
        value: "true"
```

- [ ] **Step 2: Create `evolution.Dockerfile`**

```dockerfile
FROM atendai/evolution-api:latest
```

(Single line — we just pin the upstream image; no custom build steps needed.)

- [ ] **Step 3: Commit**

```
git add render.yaml evolution.Dockerfile
git commit -m "chore: render.yaml — add Evolution API Docker service with persistent disk"
```

---

## Task 12: Update `.env.example` and run full smoke-test

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Update `.env.example`**

Open `.env.example` and replace/extend with:

```dotenv
# LLM
LLM_API_KEY=your_openrouter_key
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=deepseek/deepseek-chat-v3-0324:free

# Evolution API (WhatsApp gateway)
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=your_evolution_api_key
EVOLUTION_INSTANCE=retailmind

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=your_supabase_service_role_key

# Google OAuth (for retailer Google Sheet connection)
GOOGLE_OAUTH_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your_client_secret
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Google Sheets service account (local dev fallback)
GOOGLE_SERVICE_ACCOUNT_JSON=./service-account.json

# App
APP_BASE_URL=http://localhost:8000
RETAILMIND_CONFIG=./config/retailers.yaml
```

- [ ] **Step 2: Run the full test suite**

```
pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 3: Run the Phase 1–3 smoke-tests (no external services)**

```
python -m app.connectors.csv_loader data/sample_sales.csv
python -m app.analytics.engine data/sample_sales.csv
python -m app.ai.narrator data/sample_sales.csv
```
Expected: each prints output without error. YAML fallback means no Supabase needed locally.

- [ ] **Step 4: Commit**

```
git add .env.example
git commit -m "chore: update .env.example — Evolution/Supabase/OAuth vars, remove Twilio"
```

---

## Self-Review Checklist

After completing all tasks, verify:

- [ ] `pytest tests/ -v` — all green
- [ ] `grep -r "twilio" app/` returns nothing (Twilio fully removed)
- [ ] `python -m app.analytics.engine data/sample_sales.csv` still works (Phase 2 smoke-test)
- [ ] `python -m app.ai.narrator data/sample_sales.csv` still works (Phase 3 smoke-test)
- [ ] `db/migrations/001_initial_schema.sql` has been run in Supabase dashboard
- [ ] Evolution API service deployed on Render, QR scanned
- [ ] `EVOLUTION_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `GOOGLE_OAUTH_*` set in Render env
- [ ] Evolution webhook URL pointed at `https://<app>.onrender.com/webhook/whatsapp`
- [ ] `GOOGLE_OAUTH_REDIRECT_URI` added as authorised redirect URI in Google Cloud Console
