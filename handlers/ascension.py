"""/ascension —— 飞升试炼与账号级被动。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ascension as CFG
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             button_grid, consume_action_callback,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show)
from services import ascension, character

router = Router()


async def render_ascension(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    state = await ascension.get(user_id)
    spent = state.get("spent", {})
    title = CFG.ascension_title(state["level"])
    title_line = f"　尊号：「{title}」" if title else ""
    lines = [
        "🌌 飞升",
        f"飞升点：{state['points']}　总阶：{state['level']}{title_line}　道行：{char.daohang}",
        f"飞升试炼：化神圆满可挑战，消耗道行 {CFG.TRIAL_DAOHANG_COST}，得飞升点 {CFG.TRIAL_POINT_REWARD}。",
        (f"溢出凝点：本周 {state['overflow_week_points']}/{CFG.OVERFLOW_WEEKLY_CAP}　"
         f"道痕 {state['overflow_remainder']}/{CFG.OVERFLOW_CULTIVATION_PER_POINT}"),
        "—— 被动 ——",
    ]
    buttons = [InlineKeyboardButton(
        text="挑战飞升试炼",
        callback_data=await action_callback_data(user_id, "asc:trial"))]
    for key, name in CFG.PASSIVES.items():
        lvl = int(spent.get(key, 0))
        lines.append(f"{name}：{lvl}/{CFG.PASSIVE_CAP}（每级 +1%）")
        if lvl < CFG.PASSIVE_CAP:
            buttons.append(InlineKeyboardButton(
                text=f"升级 {name}",
                callback_data=await action_callback_data(user_id, f"asc:up:{key}")))
    if state["tianmen_unlocked"]:
        tianmen_title = f"　称谓：「{state['tianmen_title']}」" if state["tianmen_title"] else ""
        lines.extend([
            "—— 叩问天门 ——",
            f"天门：第 {state['tianmen_level']} 重{tianmen_title}",
            f"下一重：{state['tianmen_progress']}/{state['tianmen_next_cost']}",
        ])
        if state["points"] > 0:
            for amount in CFG.TIANMEN_CONTRIBUTIONS:
                buttons.append(InlineKeyboardButton(
                    text=f"投入 {amount} 点",
                    callback_data=await action_callback_data(user_id, f"asc:tm:{amount}")))
            buttons.append(InlineKeyboardButton(
                text="全部投入天门",
                callback_data=await action_callback_data(user_id, "asc:tm:all")))
    else:
        lines.append("叩问天门：四项飞升被动圆满后开放。")
    rows = button_grid(buttons)
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s == "ok" and "points" in res:
        return f"飞升试炼成功，消耗道行 {res['cost']}，获得飞升点 {res['points']}。"
    if s == "ok":
        title = res.get("title") or ""
        unlock = f"　尊号「{title}」解锁！" if title else ""
        return f"{res['name']} 被动升至 {res['level']} 级。{unlock}"
    if s == "tianmen_ok":
        lines = [
            f"已向天门投入飞升点 {res['spent']}，余 {res['points']} 点。",
            f"天门第 {res['level']} 重，下一重进度 {res['progress']}/{res['next_cost']}。",
        ]
        if res.get("crossed"):
            lines.append(f"本次叩开至第 {res['level']} 重。")
        if res.get("title"):
            lines.append(f"当前称谓：「{res['title']}」。")
        if res.get("rewards"):
            rewards = "、".join(f"{row['name']}×{row['qty']}" for row in res["rewards"])
            lines.append(f"天门赐下绑定奖励：{rewards}。")
        return "\n".join(lines)
    if s == "locked":
        return "化神圆满后方可挑战飞升试炼。"
    if s == "weekly_done":
        return "本周飞升试炼已完成，下周再来。"
    if s == "no_daohang":
        return f"道行不足（需 {res['need']}，现有 {res['have']}）。"
    if s == "no_points":
        return f"飞升点不足（需 {res['need']}，现有 {res['have']}）。"
    if s == "passives_not_max":
        return "四项飞升被动均臻圆满后，方可叩问天门。"
    if s == "bad_amount":
        return "投入数目有误，天门未受此礼。"
    if s == "max":
        return f"此被动已达上限 {res['cap']} 级。"
    if s == "bad_passive":
        return "无此飞升被动。"
    if s == "missing":
        return NEED_START
    return "飞升未成。"


@router.message(Command("ascension"))
async def cmd_ascension(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_ascension(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:ascension")
async def cb_ascension(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_ascension(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("asc:"))
async def cb_ascension_action(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("asc:"):
        return
    if action == "asc:trial":
        res = await ascension.trial(callback.from_user.id)
    elif action.startswith("asc:tm:"):
        raw_amount = action.rsplit(":", 1)[1]
        amount = None if raw_amount == "all" else int(raw_amount)
        res = await ascension.contribute_tianmen(callback.from_user.id, amount)
    else:
        res = await ascension.upgrade_passive(callback.from_user.id, action.rsplit(":", 1)[1])
    await show(callback, _result_text(res), section_back_markup("↩️ 返回飞升", "nav:ascension"))
    await callback.answer()
