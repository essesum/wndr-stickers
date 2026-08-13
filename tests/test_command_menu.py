"""Нативное меню Telegram должно помогать в личке, а не жить только в /help."""
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SetMyCommands
from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)

from bot.main import PRIVATE_COMMANDS, sync_private_commands


def test_private_command_menu_contains_user_facing_pack_actions():
    assert [command.command for command in PRIVATE_COMMANDS] == [
        "pack",
        "zip",
        "history",
        "delete",
        "style",
        "quota",
        "help",
    ]
    assert all(command.description for command in PRIVATE_COMMANDS)
    assert "stats" not in {command.command for command in PRIVATE_COMMANDS}


@pytest.mark.asyncio
async def test_command_menu_is_registered_only_for_private_chats():
    bot = AsyncMock()

    assert await sync_private_commands(bot) is True

    assert [
        type(call.kwargs["scope"])
        for call in bot.delete_my_commands.await_args_list
    ] == [
        BotCommandScopeDefault,
        BotCommandScopeAllGroupChats,
        BotCommandScopeAllChatAdministrators,
    ]
    bot.set_my_commands.assert_awaited_once()
    commands = bot.set_my_commands.await_args.args[0]
    scope = bot.set_my_commands.await_args.kwargs["scope"]
    assert commands == list(PRIVATE_COMMANDS)
    assert isinstance(scope, BotCommandScopeAllPrivateChats)


@pytest.mark.asyncio
async def test_command_menu_sync_failure_does_not_block_bot_start(caplog):
    bot = AsyncMock()
    bot.set_my_commands.side_effect = TelegramAPIError(
        method=SetMyCommands(commands=[]), message="temporary"
    )

    assert await sync_private_commands(bot) is False
    assert "не удалось синхронизировать" in caplog.text