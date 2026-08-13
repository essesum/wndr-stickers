"""Что человек имел в виду: нарисовать, удалить, вернуть или посмотреть пак.

Люди пишут боту живым языком. Разбор намеренно тупой и предсказуемый: список
глаголов, а не угадывание. Всё, что не опознано явно, считается фразой для
стикера — это поведение по умолчанию и оно не должно ломаться от новых
формулировок.
"""
# ruff: noqa: SIM905 — компактные словари ниже намеренно записаны строками
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

#: Просьба нарисовать картинку без надписи. Проверяется только в начале текста
#: (или сразу после глагола рисования): «без текста» в середине фразы — это
#: часть фразы, а не команда.
_TEXTLESS_PREFIXES = (
    "без текста",
    "без надписи",
    "без слов",
    "картинку",
    "картинка",
    "иллюстрацию",
    "иллюстрация",
)

#: Существительные-картинки для подсказки «а может, без текста?». Список
#: намеренно тупой словарь, а не угадывание: не совпало — бот просто рисует
#: обычный стикер, ничего не ломается.
_VISUAL_WORDS = frozenset(
    "роза розы кот кота котик котика кошка сердце сердечко "
    "звезда звезды звёзды костер костёр огонь пламя цветок цветы ромашка "
    "гора горы молния хинкали пельмень пельмени булка хлеб компас "
    "спичка спички чай кофе чашка книга свеча волна море птица бабочка гриб "
    "грибы ключ корона короне якорь ракета планета радуга кактус арбуз лимон "
    "вишня клубника рука ладонь крыло череп кристалл зеркало колокол подкова "
    "клевер перо лист дерево ёлка елка снежинка облако дождь зонт шляпа очки "
    "часы лампа лампочка змея тигр лев медведь волк лиса сова орёл орел кит "
    "рыба дельфин маяк корабль лодка велосипед".split()
)

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
    #: Стикер-картинка без надписи: «без текста костёр», «картинку две розы».
    ILLUSTRATE = "illustrate"
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


def _textless_rest(text: str) -> str | None:
    """«без текста костёр» -> «костёр»; не команда — None."""
    lowered = text.lower()
    for prefix in _TEXTLESS_PREFIXES:
        if lowered.startswith(prefix):
            rest = text[len(prefix) :]
            if rest and not rest[0].isspace() and rest[0] not in _QUOTES:
                continue
            return rest.strip()
    return None


def suggest_textless(phrase: str) -> bool:
    """Похожа ли фраза на описание картинки, а не на реплику для плашки."""
    words = [w.strip(".,!?…").lower() for w in phrase.split()]
    if not 1 <= len(words) <= 3:
        return False
    if any(ch in phrase for ch in "?!"):
        return False
    return any(w in _VISUAL_WORDS for w in words)


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
        textless = _textless_rest(_strip_quotes(rest))
        if textless:
            return Intent(Action.ILLUSTRATE, _strip_quotes(textless), force, addressed)
        return Intent(Action.DRAW, _strip_quotes(rest), force, addressed)

    textless = _textless_rest(raw)
    if textless:
        return Intent(Action.ILLUSTRATE, _strip_quotes(textless), force, addressed)

    return Intent(Action.DRAW, _strip_quotes(raw), force, addressed)
