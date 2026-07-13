"""/path —— 道途选择 / 升阶 / 转修。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import dao_paths as CFG
from config.items import format_bonus
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             button_grid, consume_action_callback,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show)
from services import character, dao_path

router = Router()


def _bonus_text(bonuses: dict) -> str:
    if not bonuses:
        return "无"
    return format_bonus(bonuses)


async def render_path(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    paths = await dao_path.list_paths(user_id)
    buttons = []
    lines = ["🧭 道途", f"道行：{char.daohang}"]
    if paths:
        lines.append("—— 已悟道途 ——")
        unlocked = {p["path_key"] for p in paths}
        for p in paths:
            mark = "（当前）" if p["active"] else ""
            refine = f"·淬炼{p['refine']}" if p.get("refine") else ""
            lines.append(f"{p['name']}·{p['rank_name']}{refine}{mark}：{_bonus_text(p['bonuses'])}")
            if p["active"]:
                buttons.append(InlineKeyboardButton(
                    text=f"升阶 {p['name']}",
                    callback_data=await action_callback_data(user_id, f"path:rank:{p['path_key']}")))
                buttons.append(InlineKeyboardButton(
                    text=f"淬炼 {p['name']}",
                    callback_data=await action_callback_data(user_id, f"path:refine:{p['path_key']}")))
            else:
                buttons.append(InlineKeyboardButton(
                    text=f"转修 {p['name']}",
                    callback_data=await action_callback_data(user_id, f"path:switch:{p['path_key']}")))
    else:
        unlocked = set()
        lines.append(f"元婴初期起可择一道途，首条免费。当前需至 {CFG.UNLOCK_REALM} 阶境界。")
    has_path = bool(paths)
    for key, cfg in CFG.DAO_PATHS.items():
        if key in unlocked:
            continue
        lines.append(f"{cfg['name']}：{cfg['role']}")
        op = "switch" if has_path else "unlock"
        label = "转修" if has_path else "选择"
        buttons.append(InlineKeyboardButton(
            text=f"{label} {cfg['name']}",
            callback_data=await action_callback_data(user_id, f"path:{op}:{key}")))
    rows = button_grid(buttons)
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s in {"unlocked", "active"}:
        return f"已选择道途：{res['path']}。"
    if s == "need_switch":
        return f"若要改修 {res['path']}，需使用转修。"
    if s == "ok" and "rank_name" in res:
        return f"{res['path']} 升至 {res['rank_name']}。"
    if s == "refine_ok":
        return f"{res['path']} 淬炼至第 {res['level']} 层（耗道行 {res['cost']}）。"
    if s == "refine_max":
        return "此道途淬炼已臻圆满。"
    if s == "ok":
        return f"转修成功，当前道途：{res['path']}（耗灵石 {res['cost']}）。"
    if s == "locked":
        return "境界未足，元婴初期起方可择道途。"
    if s == "not_unlocked":
        return "尚未悟得此道途。"
    if s == "max":
        return "此道途已臻当前最高阶。"
    if s == "no_daohang":
        return f"道行不足（需 {res['need']}，现有 {res['have']}）。"
    if s == "no_ascension_points":
        return f"飞升点不足（需 {res['need']}，现有 {res['have']}）。"
    if s == "no_material":
        return f"材料不足：{res['item']}（需 {res['need']}，现有 {res['have']}）。"
    if s == "cooldown":
        days = max(1, (res["remain"] + 86399) // 86400)
        return f"转修冷却未过，约余 {days} 日。"
    if s == "no_stone":
        return f"灵石不足（需 {res['need']}，现有 {res['have']}）。"
    if s == "no_token":
        return f"缺少 {res['item']}。"
    if s == "already_active":
        return "此道途已是当前修行方向。"
    if s == "missing":
        return NEED_START
    return "道途未成。"


@router.message(Command("path"))
async def cmd_path(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_path(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:path")
async def cb_path(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_path(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("path:"))
async def cb_path_action(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("path:"):
        return
    parts = action.split(":", 2)
    op, key = parts[1], parts[2]
    if op == "unlock":
        res = await dao_path.unlock(callback.from_user.id, key)
    elif op == "rank":
        res = await dao_path.rank_up(callback.from_user.id, key)
    elif op == "refine":
        res = await dao_path.refine(callback.from_user.id, key)
    else:
        res = await dao_path.switch(callback.from_user.id, key)
    await show(callback, _result_text(res), section_back_markup("↩️ 返回道途", "nav:path"))
    await callback.answer()
