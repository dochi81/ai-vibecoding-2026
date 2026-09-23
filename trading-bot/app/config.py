"""Application configuration loaded from the local .env file."""

from decimal import Decimal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings. Secrets stay in .env and are never hard-coded in Python."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    toss_client_id: str = ""
    toss_client_secret: str = ""
    toss_api_base_url: str = "https://openapi.tossinvest.com"
    database_url: str
    live_trading: bool = False
    paper_initial_cash: Decimal = Decimal("10000000")


settings = Settings()
