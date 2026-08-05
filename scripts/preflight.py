"""Проверка перед запуском: всё ли на месте, чтобы бот поднялся и работал.

Ничего не меняет и никуда не пишет — только смотрит.
Запуск: ./.venv/bin/python scripts/preflight.py
"""
from __future__ import annotations

import asyncio
import shutil
import sys

from skill.wndr_stickers.src import community_memory
from skill.wndr_stickers.src.config import get_settings

OK, FAIL, WARN = "  ✓", "  ✗", "  !"


async def main() -> int:
    s = get_settings()
    problems = 0

    print("Токен и владелец")
    if s.telegram_bot_token:
        print(f"{OK} токен на месте ({len(s.telegram_bot_token)} символов)")
    else:
        print(f"{FAIL} TELEGRAM_BOT_TOKEN пуст — запусти scripts/set_token.sh")
        problems += 1
    if s.telegram_owner_id:
        print(f"{OK} владелец бота: {s.telegram_owner_id}")
    else:
        print(f"{FAIL} TELEGRAM_OWNER_ID пуст")
        problems += 1
    print(f"{OK} владелец пака: {s.sticker_pack_owner}")
    print(f"{OK} модераторы: {sorted(s.moderators) or 'только владелец'}")

    print("\nСтиль")
    for label, path in (("референс", s.reference_sheet_path), ("шрифт", s.font_path)):
        if path.exists():
            print(f"{OK} {label}: {path.name}")
        else:
            print(f"{FAIL} {label} не найден: {path}")
            problems += 1

    print("\nГенерация картинок")
    print(f"{OK} цепочка: {' -> '.join(s.provider_chain)}")
    if "codex" in s.provider_chain:
        if shutil.which("codex"):
            print(f"{OK} codex в PATH, модель {s.codex_model}")
        else:
            print(f"{FAIL} codex не найден в PATH")
            problems += 1

    print("\nПамять сообщества")
    if not s.duplicate_check:
        print(f"{WARN} проверка повторов выключена")
    elif await community_memory.ensure_collection():
        print(f"{OK} коллекция {community_memory.COLLECTION} доступна")
        probe = await community_memory.embed("проверка")
        if probe:
            print(f"{OK} эмбеддер отвечает ({len(probe)} измерений)")
        else:
            print(f"{WARN} эмбеддер молчит — повторы ловиться не будут")
    else:
        print(f"{WARN} Qdrant недоступен — повторы ловиться не будут")

    print("\nПути")
    print(f"{OK} стикеры: {s.stickers_dir}")
    print(f"{OK} база:    {s.db_path}")

    print()
    if problems:
        print(f"Не готов: {problems} проблем(ы) выше.")
    else:
        print("Всё на месте. Запуск: ./.venv/bin/python -m bot.main")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
