"""Проверка фразы перед генерацией.

Бот открыт сообществу, значит на вход прилетит что угодно. Задача — не цензура
лексики (в самом паке живут «фейхуевого» и «кто сдох, тот — лох»), а защита от
того, что ломает стикер или бота: простыни, ссылки, спам, чужая графика.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHARS = 60
MAX_WORDS = 8
MIN_CHARS = 2

#: Кириллица, латиница, цифры, пробел и знаки, которые встречаются на эталонном листе.
ALLOWED_RE = re.compile(r"^[\w\s\-—–…!?,.:;'\"«»()*]+$", re.UNICODE)
URL_RE = re.compile(r"(https?://|www\.|t\.me/|@\w{3,})", re.IGNORECASE)
REPEAT_RE = re.compile(r"(.)\1{5,}")

#: Отказ не по морали, а по тому, что такое нельзя раздавать сообществу.
BLOCKLIST = (
    "зиг",
    "heil",
    "hitler",
    "террор",
    "убей себя",
)


@dataclass
class Verdict:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def check_phrase(phrase: str) -> Verdict:
    text = phrase.strip()

    if len(text) < MIN_CHARS:
        return Verdict(False, "Слишком коротко — напиши фразу целиком.")
    if len(text) > MAX_CHARS:
        return Verdict(
            False,
            f"Слишком длинно: {len(text)} символов, влезает до {MAX_CHARS}. "
            "На стикере должна читаться короткая фраза.",
        )
    if len(text.split()) > MAX_WORDS:
        return Verdict(False, f"Больше {MAX_WORDS} слов на стикере не прочитать.")
    if URL_RE.search(text):
        return Verdict(False, "Ссылки и упоминания на стикер не ставим.")
    if REPEAT_RE.search(text):
        return Verdict(False, "Похоже на набор символов — попробуй осмысленную фразу.")
    if not ALLOWED_RE.match(text):
        bad = sorted({c for c in text if not ALLOWED_RE.match(c)})
        return Verdict(False, f"Эти символы набрать не смогу: {' '.join(bad)}")

    lowered = text.lower()
    for word in BLOCKLIST:
        if word in lowered:
            return Verdict(False, "Такую фразу в общий пак не отдам.")

    if text.count("*") % 2 != 0:
        return Verdict(
            False, "Звёздочки для акцента ставятся парой: «Это не *тантра*»."
        )

    return Verdict(True)
