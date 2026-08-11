"""Что человек имел в виду: нарисовать, удалить, вернуть или посмотреть пак.

Люди пишут боту живым языком. Разбор намеренно тупой и предсказуемый: список
глаголов, а не угадывание. Всё, что не опознано явно, считается фразой для
стикера — это поведение по умолчанию и оно не должно ломаться от новых
формулировок.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_QUOTES = '"“”«»„‘’\''

_DRAW_VERBS = ("сделай", "создай", "нарисуй", "сгенерируй", "сделать", "нарисовать")
_DELETE_VERBS = ("удали", "убери", "удалить", "убрать", "снеси", "выкинь")
#: Возврата в паке больше нет — «передумал» решается новой генерацией. Глаголы
#: оставлены здесь, чтобы «верни в пак …» не ушло молча рисоваться как фраза:
#: человек ждал возврата, ему нужен ответ, а не стикер со словом «верни».
_GONE_VERBS = ("верни", "вернуть", "восстанови", "восстановить")
_LIST_PHRASES = (
    "что в паке",
    "покажи пак",
    "список стикеров",
    "что уже есть",
    "покажи стикеры",
)

_SCOPE_RE = re.compile(r"^\s*(?:из|в)\s+(?:стикер)?пак\w*\s*", re.IGNORECASE)

_HELP_RE = re.compile(
    r"^(?:"
    r"что\s+(?:ты\s+)?(?:умеешь|можешь|делаешь)"
    r"|что\s+(?:это\s+)?за\s+бот"
    r"|как\s+(?:(?:тобой|ты)\s+)?(?:пользоваться|работать|работаешь)"
    r"|как\s+это\s+работает"
    r"|ты\s+(?:кто|что)"
    r"|кто\s+ты"
    r"|помощь|помоги|хелп|справка|инструкция"
    r"|what\s+can\s+you\s+do|help"
    r")\b[\s?!.]*$",
    re.IGNORECASE,
)


class Action(Enum):
    DRAW = "draw"
    DELETE = "delete"
    #: Просьба вернуть удалённое. Возврата нет — бот объясняет это, а не рисует.
    GONE = "gone"
    LIST = "list"
    HELP = "help"


@dataclass(frozen=True)
class Intent:
    action: Action
    phrase: str
    force: bool = False
    addressed: bool = True


def _strip_quotes(text: str) -> str:
    text = text.strip()
    while len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return text


def _starts_with(text: str, verbs: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for verb in verbs:
        if lowered.startswith(verb):
            rest = text[len(verb) :]
            if rest and not rest[0].isspace() and rest[0] not in _QUOTES:
                continue
            return rest.strip()
    return None


def parse(
    text: str,
    *,
    bot_username: str | None = None,
    require_mention: bool = True,
) -> Intent:
    """Разобрать сообщение; в группе без тега вернуть addressed=False."""
    raw = (text or "").strip()

    addressed = True
    if bot_username:
        mention = re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)
        if mention.search(raw):
            raw = mention.sub(" ", raw).strip()
        elif require_mention:
            addressed = False

    force = raw.startswith("!")
    if force:
        raw = raw[1:].strip()

    lowered = raw.lower()
    if not force and _HELP_RE.match(raw):
        return Intent(Action.HELP, raw, force, addressed)

    for marker in _LIST_PHRASES:
        if lowered.startswith(marker):
            return Intent(Action.LIST, "", force, addressed)

    rest = _starts_with(raw, _DELETE_VERBS)
    if rest is not None:
        rest = _SCOPE_RE.sub("", rest)
        return Intent(Action.DELETE, _strip_quotes(rest), force, addressed)

    rest = _starts_with(raw, _GONE_VERBS)
    if rest is not None:
        rest = _SCOPE_RE.sub("", rest)
        return Intent(Action.GONE, _strip_quotes(rest), force, addressed)

    rest = _starts_with(raw, _DRAW_VERBS)
    if rest is not None:
        rest = _SCOPE_RE.sub("", rest)
        return Intent(Action.DRAW, _strip_quotes(rest), force, addressed)

    return Intent(Action.DRAW, _strip_quotes(raw), force, addressed)
