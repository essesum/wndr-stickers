"""Разбор намерения: человек пишет боту живым языком, а не только чистые фразы.

Найдено на живом боте: «сделай "я так чувствую"» ушло на стикер целиком, вместе
со словом «сделай» и кавычками. А «удали из пака ...» бот принял за ещё одну
фразу и нарисовал её.
"""
import pytest

from skill.wndr_stickers.src.intent import Action, parse

# --- обычная фраза остаётся фразой -------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Со мной все нормально",
        "Я приношу весь свой объем",
        "было!",
        "Это не *тантра*",
        "Делать шаги и собирать результаты",
    ],
)
def test_plain_phrase_is_drawn_as_is(text):
    got = parse(text)
    assert got.action is Action.DRAW
    assert got.phrase == text


# --- просьба нарисовать -------------------------------------------------------

def test_make_command_strips_the_verb_and_quotes():
    got = parse('сделай "я так чувствую"')
    assert got.action is Action.DRAW
    assert got.phrase == "я так чувствую"


@pytest.mark.parametrize("verb", ["сделай", "Сделай", "создай", "нарисуй", "сгенерируй"])
def test_every_make_verb_is_understood(verb):
    assert parse(f'{verb} «я так чувствую»').phrase == "я так чувствую"


def test_make_without_quotes_still_works():
    assert parse("сделай я так чувствую").phrase == "я так чувствую"


def test_quotes_alone_are_stripped():
    assert parse('"я так чувствую"') == parse("я так чувствую")
    assert parse("«я так чувствую»").phrase == "я так чувствую"


# --- просьба удалить ----------------------------------------------------------

def test_delete_is_not_a_phrase_to_draw():
    got = parse('удали из пака "я так чувствую"')
    assert got.action is Action.DELETE
    assert got.phrase == "я так чувствую"


@pytest.mark.parametrize(
    "text",
    [
        'удали "я так чувствую"',
        'убери из пака "я так чувствую"',
        'удалить "я так чувствую"',
        'убрать из пака "я так чувствую"',
        'Удали из пака «я так чувствую»',
    ],
)
def test_every_delete_wording_is_understood(text):
    got = parse(text)
    assert got.action is Action.DELETE
    assert got.phrase == "я так чувствую"


def test_delete_without_target_asks_for_one():
    got = parse("удали из пака")
    assert got.action is Action.DELETE
    assert got.phrase == ""


# --- «!» форсирует рисование --------------------------------------------------

def test_bang_prefix_forces_drawing():
    got = parse("!Со мной все нормально")
    assert got.action is Action.DRAW
    assert got.force is True
    assert got.phrase == "Со мной все нормально"


def test_bang_does_not_leak_into_the_phrase():
    assert "!" not in parse("!было").phrase


def test_exclamation_inside_a_phrase_is_kept():
    """«было!» — это фраза пака, восклицательный знак в конце трогать нельзя."""
    got = parse("было!")
    assert got.phrase == "было!"
    assert got.force is False


# --- список ------------------------------------------------------------------

def test_list_request_is_recognised():
    for text in ["что в паке", "покажи пак", "список стикеров"]:
        assert parse(text).action is Action.LIST, text


# --- бот живёт в общем чате сообщества ----------------------------------------

BOT = "WNDR_stickers_bot"


def test_mention_is_stripped_from_the_phrase():
    """В канале к боту обращаются тегом — тег не должен попасть на стикер."""
    got = parse(f'@{BOT} сделай "я так чувствую"', bot_username=BOT)
    assert got.addressed is True
    assert got.phrase == "я так чувствую"
    assert BOT not in got.phrase


def test_mention_at_the_end_also_works():
    got = parse(f'сделай "я так чувствую" @{BOT}', bot_username=BOT)
    assert got.addressed is True
    assert got.phrase == "я так чувствую"


def test_mention_alone_with_a_quoted_phrase():
    got = parse(f'@{BOT} «Делать шаги и собирать результаты»', bot_username=BOT)
    assert got.addressed is True
    assert got.phrase == "Делать шаги и собирать результаты"


def test_mention_is_case_insensitive():
    got = parse(f'@{BOT.lower()} было!', bot_username=BOT)
    assert got.addressed is True
    assert got.phrase == "было!"


def test_group_message_without_mention_is_not_addressed():
    """Иначе бот нарисует стикер на каждое сообщение в чате сообщества."""
    got = parse("да я тоже так чувствую", bot_username=BOT)
    assert got.addressed is False


def test_someone_elses_mention_is_not_ours():
    got = parse("@other_bot сделай стикер", bot_username=BOT)
    assert got.addressed is False


def test_private_chat_needs_no_mention():
    """В личке тег не нужен: там любое сообщение — обращение к боту."""
    got = parse("Со мной все нормально", bot_username=BOT, require_mention=False)
    assert got.addressed is True
    assert got.phrase == "Со мной все нормально"


def test_delete_through_a_mention():
    got = parse(f'@{BOT} удали из пака "я так чувствую"', bot_username=BOT)
    assert got.action is Action.DELETE
    assert got.phrase == "я так чувствую"


def test_without_bot_username_everything_is_addressed():
    """Обратная совместимость: не знаем имени бота — ведём себя как в личке."""
    assert parse("Со мной все нормально").addressed is True


# --- вопрос о возможностях ----------------------------------------------------
# «что ты умеешь?» ушло на стикер вместо ответа — стикер №4 в живой базе.

@pytest.mark.parametrize(
    "text",
    [
        "что ты умеешь?",
        "Что ты умеешь",
        "что умеешь?",
        "что ты можешь",
        "как пользоваться",
        "как тобой пользоваться?",
        "помощь",
        "ты кто?",
        "что это за бот",
    ],
)
def test_question_about_the_bot_is_not_a_sticker(text):
    got = parse(text)
    assert got.action is Action.HELP, f"{text!r} должно быть вопросом, а не фразой"


def test_help_keeps_the_original_text_for_the_reply():
    """Ответ приглашает сделать стикер из этой же фразы, значит текст нужен."""
    got = parse("что ты умеешь?")
    assert got.phrase == "что ты умеешь?"


def test_a_phrase_that_merely_contains_a_question_mark_is_still_a_sticker():
    assert parse("Я получаю сейчас удовольствие?").action is Action.DRAW


def test_forcing_turns_a_question_into_a_sticker():
    """Если человек правда хочет стикер «что ты умеешь?» — «!» это разрешает."""
    got = parse("!что ты умеешь?")
    assert got.action is Action.DRAW
    assert got.phrase == "что ты умеешь?"


def test_help_works_through_a_mention():
    got = parse(f"@{BOT} что ты умеешь?", bot_username=BOT)
    assert got.action is Action.HELP
    assert got.addressed is True


def test_natural_how_do_you_work_is_help():
    assert parse("как ты работаешь?").action is Action.HELP


@pytest.mark.parametrize(
    "text",
    [
        'верни в пак "я так чувствую"',
        "восстанови из стикерпака «я так чувствую»",
    ],
)
def test_restore_is_not_drawn_as_a_new_sticker(text):
    got = parse(text)
    assert got.action is Action.RESTORE
    assert got.phrase == "я так чувствую"
