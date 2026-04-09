"""
App settings — Phase 6.5 SEC-06.

Loads from data/.env (chmod 600). All fields default to "" / 0 so the app
boots cleanly even if the .env file is absent or partially filled.

Usage:
    from app.settings import settings
    token = settings.telegram_bot_token
"""

from pathlib import Path

from pydantic_settings import BaseSettings

_ENV_PATH = Path(__file__).parent.parent / "data" / ".env"


class _Settings(BaseSettings):
    openweather_key: str = ""
    news_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_allowed_user_id: int = 0
    hue_bridge_ip: str = ""
    hue_bridge_token: str = ""
    llm_model: str = "gemma4:e4b"

    class Config:
        env_file = str(_ENV_PATH)
        env_file_encoding = "utf-8"


settings = _Settings()
