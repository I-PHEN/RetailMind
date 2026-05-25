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

    # Wuzapi (WhatsApp gateway — local Docker)
    wuzapi_api_url: str = "http://localhost:8080"
    wuzapi_token: str = ""

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Google OAuth (for Sheets connection during onboarding)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    google_api_key: str = ""  # for the Google Picker widget on the sheet-picker page

    # Google Sheets service account (legacy / dev fallback)
    google_service_account_json: str = "./service-account.json"

    # App
    retailmind_config: str = "./config/retailers.yaml"
    app_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
