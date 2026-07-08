"""/craft —— 炼丹炼器。"""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config.items import item_name
from config.recipes import RECIPES
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             button_grid, consume_action_callback,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show)
from services import character, crafting

router = Router()

CRAFT_CATEGORIES = [
    ("alchemy", "炼丹", "💊 炼丹"),
    ("forge", "炼器", "⚒️ 炼器"),
]
_CAT_TITLE = {cat: title for cat, title, _ in CRAFT_CATEGORIES}
_CAT_ICON = {"alchemy": "💊", "forge": "⚒️"}


def _collected_text(item: dict) -> str:
    text = f"{item['name']}×{item.get('qty', 1)}"
    if item.get("daohang"):
        text += f"（道行+{item['daohang']}）"
    return text


def _duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = (seconds + 59) // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小时 {rest} 分钟" if rest else f"{hours} 小时"


async def render_craft(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    collected = await crafting.collect_ready(user_id)
    active = await crafting.active_job(user_id)
    lines = ["💊 炼丹炼器"]
    if collected:
        lines.append("出炉：" + "、".join(_collected_text(c) for c in collected))
    rows = []
    if active:
        recipe = RECIPES[active["recipe_key"]]
        remain = max(0, active["finish_at"] - int(time.time()))
        lines.append(f"炉中：{recipe['name']}，尚需 {_duration(remain)}。")
        rows.append([InlineKeyboardButton(
            text=f"🪙 灵石加速（{crafting.accelerate_cost(remain)}）",
            callback_data=await action_callback_data(user_id, "craft:fast"))])
    else:
        recipes = await crafting.available_recipes(user_id)
        grouped = {
            cat: [(key, recipe) for key, recipe in recipes if recipe["type"] == cat]
            for cat, _, _ in CRAFT_CATEGORIES
        }
        counts = [f"{title} {len(grouped[cat])}"
                  for cat, title, _ in CRAFT_CATEGORIES if grouped[cat]]
        lines.append("可炼：" + (" · ".join(counts) if counts else "筑基后方可稳控炉火"))
        entries = [
            InlineKeyboardButton(text=label, callback_data=f"craft:cat:{cat}")
            for cat, _, label in CRAFT_CATEGORIES if grouped[cat]
        ]
        rows += button_grid(entries)
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def render_craft_category(user_id: int, cat: str):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    if cat not in _CAT_TITLE:
        return await render_craft(user_id)
    recipes = [
        (key, recipe)
        for key, recipe in await crafting.available_recipes(user_id)
        if recipe["type"] == cat
    ]
    if not recipes:
        return await render_craft(user_id)

    lines = [f"{_CAT_ICON[cat]} {_CAT_TITLE[cat]}"]
    buttons = []
    for key, recipe in recipes:
        mats = "、".join(f"{item_name(k)}×{v}" for k, v in recipe["materials"].items())
        lines.append(f"- {recipe['name']}：{mats} / 🪙{recipe['stone']} / {_duration(recipe['seconds'])}")
        buttons.append(InlineKeyboardButton(
            text=f"{recipe['name']} {recipe['stone']}",
            callback_data=await action_callback_data(user_id, f"craft:start:{key}")))
    rows = button_grid(buttons)
    rows.append([InlineKeyboardButton(text="↩️ 返回炼制", callback_data="nav:craft")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s == "started":
        return f"炉火已起，开始炼制「{res['name']}」，约 {_duration(res['seconds'])} 后出炉。"
    if s == "busy":
        return "炉中已有造化，且待出炉。"
    if s == "locked":
        return "炼丹炼器需筑基后方可稳控炉火。"
    if s == "need_recipe":
        return "尚未研读对应丹方/图纸。"
    if s == "in_seclusion":
        return "道友闭关中，不宜分神开炉。"
    if s == "no_stone":
        return f"灵石不足（需 {res['need']}，余 {res['have']}）。"
    if s == "no_material":
        parts = [f"{item_name(m['item'])}：需 {m['need']}，现有 {m['have']}" for m in res["missing"]]
        return "材料不足：\n" + "\n".join(parts)
    if s == "accelerated":
        names = "、".join(_collected_text(c) for c in res["collected"]) or "炉火已催至将成"
        if res.get("cost", 0) <= 0:
            return f"炉火已成，{names}。"
        return f"消耗灵石 {res['cost']} 加速，{names}。"
    if s == "no_job":
        return "炉中空空，尚无可加速之物。"
    return "天机紊乱，炉火暂熄。"


@router.message(Command("craft"))
async def cmd_craft(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_craft(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:craft")
async def cb_craft(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_craft(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("craft:cat:"))
async def cb_craft_category(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    cat = callback.data.split(":", 2)[2]
    text, markup = await render_craft_category(callback.from_user.id, cat)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("craft:start:"))
async def cb_craft_start(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("craft:start:"):
        return
    res = await crafting.start_job(callback.from_user.id, action.split(":", 2)[2])
    await show(callback, _result_text(res), section_back_markup("↩️ 返回炼制", "nav:craft"))
    await callback.answer()


@router.callback_query(F.data.startswith("craft:fast:"))
async def cb_craft_fast(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    if await consume_action_callback(callback) != "craft:fast":
        return
    res = await crafting.accelerate(callback.from_user.id)
    await show(callback, _result_text(res), section_back_markup("↩️ 返回炼制", "nav:craft"))
    await callback.answer()
