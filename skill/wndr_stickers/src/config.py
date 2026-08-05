"""Настройки бота. Читаются из .env в корне репозитория."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    # Генерация картинок.
    # codex — GPT image по подписке ChatGPT через Codex CLI, без API-ключа.
    image_provider_chain: str = "codex,openrouter_gpt,gemini"
    codex_model: str = "gpt-5.5"
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
    pack_title: str = "WNDR Stickers"
    default_emoji: str = "🔥"
    #: Владелец набора в Telegram. Отдельно от админа бота — набор передаётся
    #: другому человеку правкой одной строки, код при этом не меняется.
    pack_owner_id: int = 0
    #: Лимит Telegram на статичный набор; дальше заводим следующий пак.
    pack_capacity: int = 120

    # Память сообщества: ловим повторы до генерации
    duplicate_check: bool = True
    duplicate_threshold: float = 0.82

    # Апрув
    require_approval: bool = True
    moderator_ids: str = ""
    #: После скольких одобренных стикеров автор добавляет в пак без очереди.
    #: 0 — доверие не выдаётся никогда.
    auto_trust_after: int = 3
    #: Чат, куда падают заявки. 0 — рассылаем модераторам в личку.
    moderation_chat_id: int = 0

    # Квоты
    rate_per_user_hour: int = 5
    rate_per_user_day: int = 20
    rate_global_day: int = 300

    # Пути
    state_dir: Path = Path("~/katya-ai/state/wndr-stickers").expanduser()
    #: Зона community/ — данные сообщества, а не Кати. Персональные данные
    #: (Telegram-ID, авторство) живут только в SQLite в state_dir и сюда не
    #: попадают: в память сеется единственный файл _context.md.
    output_dir: Path = Path("~/katya-ai/community/wndr-stickers").expanduser()

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

    @field_validator(
        "telegram_owner_id",
        "pack_owner_id",
        "moderation_chat_id",
        "pack_capacity",
        "auto_trust_after",
        mode="before",
    )
    @classmethod
    def _blank_means_zero(cls, value):
        """В .env.example эти поля документированы пустыми — пустое читаем как 0.

        Без этого бот падал на старте у всякого, кто скопировал образец как есть.
        """
        if isinstance(value, str) and not value.strip():
            return 0
        return value

    @property
    def moderators(self) -> set[int]:
        """Список модераторов. Владелец бота всегда среди них."""
        out = self._ids(self.moderator_ids)
        if self.telegram_owner_id:
            out.add(self.telegram_owner_id)
        return out

    @property
    def sticker_pack_owner(self) -> int:
        """Кому принадлежит набор. По умолчанию — владельцу бота."""
        return self.pack_owner_id or self.telegram_owner_id

    @staticmethod
    def _ids(raw: str) -> set[int]:
        out: set[int] = set()
        for chunk in raw.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.lstrip("-").isdigit():
                out.add(int(chunk))
        return out

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
