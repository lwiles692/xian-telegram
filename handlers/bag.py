from __future__ import annotations

"""/bag —— 最简储物袋。"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import auction as auction_cfg
from config.items import ITEMS, is_usable, item_name
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             button_grid, consume_action_callback,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show)
from services import character, items as item_service

router = Router()

BAG_CATEGORIES = [
    ("usable", "可使用", "可使用"),
    ("pill", "丹药突破", "丹药"),
    ("material", "材料", "材料"),
    ("page", "功法残页", "残页"),
    ("equipment", "法宝", "法宝"),
]
_CAT_TITLE = {cat: title for cat, title, _ in BAG_CATEGORIES}
_CAT_HINT = {
    "pill": "突破丹会在突破时自动消耗；可直接服用的丹药在「可使用」中操作。",
    "material": "材料用于炼制、突破或交易，本页仅查看库存。",
    "page": "残页集齐后可在「功法」中领悟。",
    "equipment": "这里只查看法宝状态；装备、强化、重铸、分解请到「功法」。",
}


def _inventory_groups(inv: list[tuple[str, int]]) -> dict:
    groups = {cat: [] for cat, _, _ in BAG_CATEGORIES}
    for key, qty in inv:
        item_type = ITEMS.get(key, {}).get("type", "")
        if is_usable(key):
            groups["usable"].append((key, qty))
        elif item_type == "pill":
            groups["pill"].append((key, qty))
        elif item_type == "page":
            groups["page"].append((key, qty))
        else:
            groups["material"].append((key, qty))
    return groups


async def render_bag(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    inv = await character.inventory(user_id)
    instances = await character.item_instances(user_id)
    groups = _inventory_groups(inv)
    lines = ["🎒 储物袋", f"🪙 灵石 {char.spirit_stone}"]
    counts = [f"{title} {len(groups[cat])}" for cat, title, _ in BAG_CATEGORIES
              if cat != "equipment" and groups[cat]]
    if instances:
        counts.append(f"法宝 {len(instances)}")
    if counts:
        lines.append("物品：" + " · ".join(counts))
    else:
        lines.append("（空空如也，去历练寻些机缘吧）")

    entries = [
        InlineKeyboardButton(text=label, callback_data=f"bag:cat:{cat}")
        for cat, _, label in BAG_CATEGORIES
        if (instances if cat == "equipment" else groups[cat])
    ]
    rows = button_grid(entries)
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def render_bag_category(user_id: int, cat: str):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    inv = await character.inventory(user_id)
    instances = await character.item_instances(user_id)
    groups = _inventory_groups(inv)
    if cat not in _CAT_TITLE:
        return await render_bag(user_id)

    has_content = bool(instances if cat == "equipment" else groups.get(cat))
    if not has_content:
        return await render_bag(user_id)

    lines = [f"🎒 {_CAT_TITLE[cat]}"]
    if cat in _CAT_HINT:
        lines.append(_CAT_HINT[cat])
    for key, qty in groups.get(cat, []):
        lines.append(f"{item_name(key)} ×{qty}")
    buttons = []
    if cat == "usable":
        for key, _qty in groups["usable"]:
            buttons.append(InlineKeyboardButton(
                text=f"使用 {item_name(key)}",
                callback_data=await action_callback_data(user_id, f"bag:use:{key}")))
    elif cat == "equipment":
        for inst in instances:
            mark = ("拍卖托管" if inst.get("status") == auction_cfg.INSTANCE_STATUS_AUCTION
                    else ("已装备" if inst["equipped_slot"] else "未装备"))
            lines.append(f"#{inst['id']} {item_name(inst['base_key'])}（{mark}）")
    rows = button_grid(buttons)
    rows.append([InlineKeyboardButton(text="↩️ 返回储物袋", callback_data="nav:bag")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s == "vital_restored":
        parts = []
        if res["hp_gain"] > 0:
            parts.append(f"气血 +{res['hp_gain']}（{res['hp']}/{res['max_hp']}）")
        if res["mp_gain"] > 0:
            parts.append(f"法力 +{res['mp_gain']}（{res['mp']}/{res['max_mp']}）")
        if res.get("cleared_unstable"):
            parts.append("道基渐稳")
        return f"服下{res['item']}，" + "，".join(parts) + "。"
    if s == "vital_full":
        return f"气血法力俱已充盈，暂不必服用{res['item']}。"
    if s == "busy_activity":
        return f"正在历练 / 秘境途中，不便服用{res['item']}，归来后再补给。"
    if s == "root_up":
        return f"炼化{res['item']}，根骨 {res['old']} → {res['new']}。"
    if s == "root_cap":
        return f"根骨已臻当前上限 {res['cap']}。"
    if s == "buff_ok":
        minutes = max(1, res["duration"] // 60)
        return f"服下{res['item']}，药力流转，增益持续 {minutes} 分钟。"
    if s == "recipe_ok":
        return f"研读{res['item']}，已掌握「{res['recipe']}」。"
    if s == "known_recipe":
        return f"「{res['recipe']}」早已烂熟于心。"
    if s == "no_item":
        return f"储物袋中没有 {res['item']}。"
    if s == "missing":
        return NEED_START
    return "此物暂不可直接使用。"


@router.message(Command("bag"))
async def cmd_bag(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_bag(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:bag")
async def cb_bag(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_bag(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("bag:cat:"))
async def cb_bag_category(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    cat = callback.data.split(":", 2)[2]
    text, markup = await render_bag_category(callback.from_user.id, cat)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("bag:use:"))
async def cb_use_item(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("bag:use:"):
        return
    res = await item_service.use(callback.from_user.id, action.split(":", 2)[2])
    await show(callback, _result_text(res), section_back_markup("↩️ 返回储物袋", "nav:bag"))
    await callback.answer()
