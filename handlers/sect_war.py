"""/sectwar —— 宗门战据点。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import sect_war as CFG
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             consume_action_callback, guard_private_callback,
                             guard_private_message, section_back_markup, show)
from services import character, sect_war

router = Router()


def _buff_text(buff: dict) -> str:
    if not buff:
        return "无"
    return "、".join(f"{k}+{v * 100:.0f}%" for k, v in buff.items())


async def render_sect_war(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    current = await sect_war.bonuses_for_user(user_id)
    lines = [
        "⚔️ 宗门战·据点",
        "占据据点可为宗门成员提供轻量 buff（会进入全局合算上限）。",
        f"当前据点加成：{_buff_text(current)}",
    ]
    rows = []
    for key, cfg in CFG.OUTPOSTS.items():
        lines.append(f"{cfg['name']}：{_buff_text(cfg.get('buff', {}))}")
        rows.append([InlineKeyboardButton(
            text=f"争夺 {cfg['name']}",
            callback_data=await action_callback_data(user_id, f"sectwar:cap:{key}"))])
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s == "ok":
        return f"据点争夺成功：{res['outpost']}，宗门积分 +{res['score']}。"
    if s == "defeated":
        return f"不敌 {res['guard']}，据点 {res['outpost']} 争夺失败，未得积分。"
    if s == "closed":
        return "据点战未开放（每周六 20:00–21:00）。"
    if s == "not_member":
        return "尚未加入宗门，不可参与宗门战。"
    if s == "no_stamina":
        return f"精力不足（需 {res['need']}，现有 {res['have']}），未进入据点战。"
    if s == "bad_outpost":
        return "无此据点。"
    if s == "missing":
        return NEED_START
    return "宗门战未成。"


@router.message(Command("sectwar"))
async def cmd_sect_war(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_sect_war(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:sectwar")
async def cb_sect_war(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_sect_war(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("sectwar:cap:"))
async def cb_sect_war_capture(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("sectwar:cap:"):
        return
    res = await sect_war.capture(callback.from_user.id, action.rsplit(":", 1)[1])
    await show(callback, _result_text(res), section_back_markup("↩️ 返回宗门战", "nav:sectwar"))
    await callback.answer()
