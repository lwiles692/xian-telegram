from __future__ import annotations

"""/auction —— 拍卖行浏览与关注。"""

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             button_grid, consume_action_callback,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show)
from services import auction, character

router = Router()


def _left_text(end_at: int) -> str:
    seconds = max(0, int(end_at))
    minutes = max(1, (seconds + 59) // 60)
    if minutes >= 60:
        return f"约 {minutes // 60} 时 {minutes % 60} 分"
    return f"约 {minutes} 分"


async def render_auction(user_id: int, now: int = None):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    now = int(time.time()) if now is None else int(now)
    rows = await auction.list_active(limit=10)
    lines = ["🔨 拍卖行", f"🪙 灵石 {char.spirit_stone}", f"在拍：{len(rows)} 场"]
    buttons = []
    if rows:
        for row in rows:
            price = row["current_bid"] if row["current_bid"] is not None else row["start_price"]
            left = _left_text(row["end_at"] - now)
            bid_text = f"当前 {price} 灵石" if row["current_bid"] is not None else f"起拍 {price} 灵石"
            lines.append(f"#{row['id']} {row['item']}×{row['qty'] or 1}：{bid_text}，{left} 收槌")
            if row["seller_id"] == user_id:
                continue
            watched = await auction.is_watching(user_id, row["id"])
            action = "unwatch" if watched else "watch"
            label = f"取消关注 #{row['id']}" if watched else f"关注 #{row['id']}"
            buttons.append(InlineKeyboardButton(
                text=label,
                callback_data=await action_callback_data(user_id, f"auc:{action}:{row['id']}")))
    else:
        lines.append("暂无在拍之物。")
    button_rows = button_grid(buttons)
    append_main_menu_return(button_rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=button_rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s == "ok" and "item" in res:
        return f"已关注 #{res['auction_id']}「{res['item']}」，被超价与临近结拍时会传讯提醒。"
    if s == "ok":
        return f"已取消关注 #{res['auction_id']}。"
    if s == "not_watching":
        return "未曾关注此拍卖。"
    if s == "self_watch":
        return "自己的拍卖不必关注，天机自会记在账上。"
    if s == "not_available":
        return "该拍卖已不可关注。"
    return "拍卖行操作未成。"


@router.message(Command("auction"))
async def cmd_auction(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_auction(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:auction")
async def cb_auction(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_auction(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("auc:"))
async def cb_auction_action(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action:
        return
    parts = action.split(":")
    if len(parts) != 3:
        await callback.answer("拍卖令牌有误。", show_alert=True)
        return
    op = parts[1]
    try:
        auction_id = int(parts[2])
    except ValueError:
        await callback.answer("拍卖令牌有误。", show_alert=True)
        return
    if op == "watch":
        res = await auction.watch(callback.from_user.id, auction_id)
    elif op == "unwatch":
        res = await auction.unwatch(callback.from_user.id, auction_id)
    else:
        await callback.answer("拍卖令牌有误。", show_alert=True)
        return
    await show(callback, _result_text(res), section_back_markup("↩️ 返回拍卖行", "nav:auction"))
    await callback.answer()
