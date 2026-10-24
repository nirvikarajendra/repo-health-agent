"""Settings read from environment variables (and the .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = None
    github_token: str | None = None
    # The agent's Gemini model, e.g. a free-tier Flash model. Never hard-coded.
    gemini_model: str | None = None
    # Only for tests/test_sql.py.
    test_database_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
