from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


class Settings(BaseModel):
    """Runtime configuration loaded from environment variables."""

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    design_model: str | None = None
    code_model: str | None = None
    test_model: str | None = None
    app_env: str = "dev"
    max_retries: int = 2

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    max_retries_raw = os.getenv("MAX_RETRIES", "2")
    try:
        max_retries = int(max_retries_raw)
    except ValueError:
        max_retries = 2
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        design_model=os.getenv("DESIGN_MODEL") or None,
        code_model=os.getenv("CODE_MODEL") or None,
        test_model=os.getenv("TEST_MODEL") or None,
        app_env=os.getenv("APP_ENV", "dev"),
        max_retries=max_retries,
    )
