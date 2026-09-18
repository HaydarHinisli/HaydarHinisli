from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    replica_env: str = 'local'
    replica_database_url: str = 'sqlite:///./replica.db'
    replica_public_base_url: str = 'http://127.0.0.1:8000'
    replica_demo_mode: bool = True
    replica_audio_analysis_enabled: bool = False
    replica_global_learning_enabled: bool = False

    openai_api_key: str | None = None
    openai_realtime_model: str = 'gpt-realtime-2.1'

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    hubspot_access_token: str | None = None
    google_calendar_access_token: str | None = None
    google_calendar_id: str = 'primary'
    salesforce_instance_url: str | None = None
    salesforce_access_token: str | None = None


@lru_cache

def get_settings() -> Settings:
    return Settings()
