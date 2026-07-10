from __future__ import annotations

"""/help —— 指南。"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config.copy import HELP, OVERFLOW_NOTICE_TITLE, VERSION_NOTICE_TITLE
from handlers.common import main_menu_return_markup, show
from services import character

router = Router()


async def render_version_notice() -> str:
    return f"{VERSION_NOTICE_TITLE}\n{await character.overflow_grace_notice()}"


async def render_help() -> str:
    return f"{HELP}\n\n{OVERFLOW_NOTICE_TITLE}\n{await character.overflow_grace_notice()}"


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(await render_help(), reply_markup=main_menu_return_markup())


@router.callback_query(F.data == "nav:help")
async def cb_help(callback: CallbackQuery):
    await show(callback, await render_help(), main_menu_return_markup())
    await callback.answer()
