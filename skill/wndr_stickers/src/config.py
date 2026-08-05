"""Настройки бота. Читаются из .env в корне репозитория."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", extra="ignore", case_sensitive=False
    )

    # Telegram
    telegram_bot_token: str = ""
    telegram_owner_id: int = 0

    # Доступ
    access_mode: str = "open"  # open | allowlist
    allowed_user_ids: str = ""

    # Генерация картинок
    image_provider_chain: str = "openrouter_gpt,gemini"
    openrouter_api_key: str = ""
    openrouter_image_model: str = "openai/gpt-5-image"
    openai_api_key: str = ""
    openai_image_model: str = "gpt-image-1"
    gemini_api_key: str = ""
    gemini_image_model: str = "gemini-3-pro-image-preview"

    https_proxy: str = ""

    # Стиль
    reference_sheet: Path = Path("assets/reference/wndr-reference-sheet.png")
    font_path: Path = Path("/System/Library/Fonts/Supplemental/Impact.ttf")
    allow_arrow_shapes: bool = False

    # Стикерпак
    pack_slug: str = "wndr"
    pack_title: str = "WNDR — More Life"
    default_emoji: str = "🔥"

    # Квоты
    rate_per_user_hour: int = 5
    rate_per_user_day: int = 20
    rate_global_day: int = 300

    # Пути
    state_dir: Path = Path("~/katya-ai/state/wndr-stickers").expanduser()
    output_dir: Path = Path("~/katya-ai/work/wndr-stickers").expanduser()

    @property
    def db_path(self) -> Path:
        return self.state_dir / "stickers.db"

    @property
    def stickers_dir(self) -> Path:
        return self.output_dir / "telegram-stickers"

    @property
    def raw_dir(self) -> Path:
        """Сырые плашки от модели — до впечатывания текста. Нужны для разбора брака."""
        return self.output_dir / "raw"

    @property
    def zip_path(self) -> Path:
        return self.output_dir / "wndr-stickers.zip"

    @property
    def reference_sheet_path(self) -> Path:
        p = self.reference_sheet
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def provider_chain(self) -> list[str]:
        return [p.strip() for p in self.image_provider_chain.split(",") if p.strip()]

    @property
    def allowlist(self) -> set[int]:
        out: set[int] = set()
        for chunk in self.allowed_user_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                out.add(int(chunk))
        if self.telegram_owner_id:
            out.add(self.telegram_owner_id)
        return out

    def user_allowed(self, user_id: int) -> bool:
        if user_id == self.telegram_owner_id:
            return True
        if self.access_mode == "open":
            return True
        return user_id in self.allowlist


@lru_cache
def get_settings() -> Settings:
    return Settings()
