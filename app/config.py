from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    admin_telegram_ids: list[int] = Field(default_factory=list)
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    card_number: str = ""
    card_holder: str = ""
    price_toman: int = 99_000
    domain: str = "ayeneh.smarbiz.sbs"
    database_url: str = "sqlite+aiosqlite:////app/data/ayeneh.db"
    min_responses_for_preview: int = 3

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> list[int]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        return [int(item.strip()) for item in str(value).split(",") if item.strip()]

    @property
    def price_label(self) -> str:
        return f"{self.price_toman:,}".replace(",", "٬")

    @property
    def card_display(self) -> str:
        digits = "".join(ch for ch in self.card_number if ch.isdigit())
        if len(digits) == 16:
            return " ".join(digits[index:index + 4] for index in range(0, 16, 4))
        return self.card_number


@lru_cache
def get_settings() -> Settings:
    return Settings()
