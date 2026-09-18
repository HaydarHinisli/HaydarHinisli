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

    # Sprint 1: JWT-based session tokens. The default is an insecure dev-only value;
    # production MUST override REPLICA_JWT_SECRET (see docs/DECISIONS.md ADR-018 —
    # full OAuth remains a documented open gap, this is the pilot-grade stepping stone).
    replica_jwt_secret: str = 'dev-insecure-change-me-in-production'
    replica_jwt_expires_minutes: int = 480

    openai_api_key: str | None = None
    openai_realtime_model: str = 'gpt-realtime-2.1'

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None

    # Sprint 2B: streaming ASR provider selection (app/streaming/asr.get_asr_provider()).
    # 'simulated' (default) is the only provider that works without credentials — see
    # docs/DECISIONS.md ADR-045. Nova-3 is Deepgram's current-generation streaming
    # model; 'de' targets German as the first language per the product brief.
    replica_asr_provider: str = 'simulated'
    deepgram_api_key: str | None = None
    deepgram_region: str = 'eu'
    deepgram_model: str = 'nova-3'
    deepgram_language: str = 'de'

    hubspot_access_token: str | None = None
    google_calendar_access_token: str | None = None
    google_calendar_id: str = 'primary'
    salesforce_instance_url: str | None = None
    salesforce_access_token: str | None = None


@lru_cache

def get_settings() -> Settings:
    return Settings()
