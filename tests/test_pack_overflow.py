"""Переполнение набора: Telegram держит 120 статичных стикеров, дальше — новый пак."""
from aiogram.exceptions import TelegramBadRequest

from skill.wndr_stickers.src.pack import is_pack_full, is_pack_missing, pack_title


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=None, message=message)


def test_full_pack_error_is_recognised():
    assert is_pack_full(_bad_request("Bad Request: STICKERS_TOO_MUCH"))


def test_full_pack_error_is_recognised_in_any_case():
    assert is_pack_full(_bad_request("bad request: stickerset_too_much"))


def test_other_errors_are_not_treated_as_full():
    assert not is_pack_full(_bad_request("Bad Request: STICKERSET_INVALID"))
    assert not is_pack_full(_bad_request("Bad Request: PEER_ID_INVALID"))


def test_missing_pack_error_is_recognised():
    assert is_pack_missing(_bad_request("Bad Request: STICKERSET_INVALID"))
    assert not is_pack_missing(_bad_request("Bad Request: STICKERS_TOO_MUCH"))


def test_first_pack_title_is_unchanged():
    assert pack_title("WNDR Stickers", 1) == "WNDR Stickers"


def test_continuation_packs_are_numbered_in_the_title():
    assert pack_title("WNDR Stickers", 2) == "WNDR Stickers (2)"
    assert pack_title("WNDR Stickers", 7) == "WNDR Stickers (7)"
