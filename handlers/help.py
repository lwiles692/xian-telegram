from __future__ import annotations

"""/help —— 指南。"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from aiogram.utils.formatting import Bold, BotCommand, Italic, Text

from bot.presentation import RichPage, answer, escape_rich_html, show
from config.copy import (
    HELP_GROUPS,
    HELP_INTRO,
    HELP_OUTRO,
    OVERFLOW_NOTICE_TITLE,
    VERSION_NOTICE_TITLE,
)
from handlers.common import main_menu_return_markup
from services import character

router = Router()


def _commands_fallback(notice: str) -> Text:
    parts = [Bold("📜 问道·指南"), "\n", Italic(HELP_INTRO)]
    for group, rows in HELP_GROUPS:
        parts.extend(["\n\n", Bold(group)])
        for command, description in rows:
            parts.extend(["\n• ", BotCommand(f"/{command}"), " — ", description])
    parts.extend([
        "\n\n", Italic(HELP_OUTRO),
        "\n\n", Bold(OVERFLOW_NOTICE_TITLE), "\n", notice])
    return Text(*parts)


def _commands_html(notice: str) -> str:
    groups = []
    for group, rows in HELP_GROUPS:
        items = "".join(
            f"<li>/{command} — {escape_rich_html(description)}</li>"
            for command, description in rows)
        groups.append(f"<h2>{escape_rich_html(group)}</h2><ul>{items}</ul>")
    return (
        "<h1>📜 问道·指南</h1>"
        f"<p><i>{escape_rich_html(HELP_INTRO)}</i></p>"
        + "".join(groups)
        + f"<p><i>{escape_rich_html(HELP_OUTRO)}</i></p>"
        + f"<h2>{escape_rich_html(OVERFLOW_NOTICE_TITLE)}</h2>"
        + f"<p>{escape_rich_html(notice)}</p>")


async def render_help() -> RichPage:
    notice = await character.overflow_grace_notice()
    return RichPage(
        page="help",
        rich_html=_commands_html(notice),
        fallback=_commands_fallback(notice),
    )


async def render_version_notice() -> RichPage:
    notice = await character.overflow_grace_notice()
    return RichPage(
        page="version_notice",
        rich_html=(
            f"<h1>{escape_rich_html(VERSION_NOTICE_TITLE)}</h1>"
            f"<p>{escape_rich_html(notice)}</p>"),
        fallback=Text(Bold(VERSION_NOTICE_TITLE), "\n", notice),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await answer(message, await render_help(), main_menu_return_markup())


@router.callback_query(F.data == "nav:help")
async def cb_help(callback: CallbackQuery):
    await show(callback, await render_help(), main_menu_return_markup())
    await callback.answer()
