from __future__ import annotations

"""交互层共用组件：主菜单、进度条、消息编辑（回调幂等）。"""

import secrets
import time
from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.formatting import Bold, ExpandableBlockQuote, Text

from bot.presentation import RichPage, escape_rich_html, show
from models import db

NEED_START = "道友尚未踏入仙途，请先发送 /start 测灵根、开启修行。"
PRIVATE_ONLY = "养成诸事请移步私聊。群中暂且只留切磋、排行与宗门播报。"
TOKEN_TTL_SECONDS = 15 * 60
TOKEN_EXPIRED = "此操作已过期或已处理，请刷新页面后再试。"


def battle_report_page(
        *, page: str, title: str, outcome: str, log: list[str],
        rewards: list[str], status: list[str]) -> RichPage:
    """构造折叠斗法战报；日志折叠，所得与状态摘要保持可见。"""
    log_rows = log or ["斗法无可记述。"]
    log_text = "\n".join(log_rows)
    fallback_parts = [
        Bold(title), "\n", outcome,
        "\n\n", ExpandableBlockQuote(Bold("斗法经过"), "\n", log_text),
    ]
    if rewards:
        fallback_parts.extend([
            "\n\n", Bold("所得机缘"),
            *[part for row in rewards for part in ("\n", row)],
        ])
    if status:
        fallback_parts.extend([
            "\n\n", Bold("当前状态"),
            *[part for row in status for part in ("\n", row)],
        ])
    reward_html = "" if not rewards else (
        "<h2>所得机缘</h2><ul>" +
        "".join(f"<li>{escape_rich_html(row)}</li>" for row in rewards) +
        "</ul>")
    status_html = "" if not status else (
        "<h2>当前状态</h2><ul>" +
        "".join(f"<li>{escape_rich_html(row)}</li>" for row in status) +
        "</ul>")
    rich_html = (
        f"<h1>{escape_rich_html(title)}</h1>"
        f"<p><b>{escape_rich_html(outcome)}</b></p>"
        "<details><summary>斗法经过</summary>"
        + "".join(f"<p>{escape_rich_html(row)}</p>" for row in log_rows)
        + "</details>" + reward_html + status_html)
    return RichPage(
        page=page,
        rich_html=rich_html,
        fallback=Text(*fallback_parts))


async def dm_link(bot) -> str:
    me = await bot.get_me()
    if me.username:
        return f"https://t.me/{me.username}?start=menu"
    return ""


def is_private_chat(chat) -> bool:
    chat_type = str(getattr(chat, "type", "")).lower()
    return chat_type == "private" or chat_type.endswith(".private")


async def action_callback_data(user_id: Optional[int], action: str) -> str:
    token = secrets.token_urlsafe(6)
    now = int(time.time())
    await db.execute(
        "INSERT INTO callback_tokens(token, user_id, action, created_at) VALUES(?,?,?,?)",
        (token, user_id, action, now))
    return f"{action}:{token}"


async def consume_action_callback(callback):
    if not callback.data or ":" not in callback.data:
        await callback.answer(TOKEN_EXPIRED, show_alert=True)
        return None
    action, token = callback.data.rsplit(":", 1)
    now = int(time.time())
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM callback_tokens WHERE token=?", (token,))
        row = await cur.fetchone()
        await cur.close()
        if (not row or row["action"] != action or row["consumed_at"] is not None
                or now - row["created_at"] > TOKEN_TTL_SECONDS
                or (row["user_id"] is not None and row["user_id"] != callback.from_user.id)):
            await callback.answer(TOKEN_EXPIRED, show_alert=True)
            return None
        await conn.execute(
            "UPDATE callback_tokens SET consumed_at=? WHERE token=?",
            (now, token))
    return action


async def cleanup_callback_tokens(now: int = None):
    """清理已消费或已过期的一次性回调 token，避免该表无限增长。"""
    now = int(time.time()) if now is None else now
    await db.execute(
        "DELETE FROM callback_tokens WHERE consumed_at IS NOT NULL OR created_at < ?",
        (now - TOKEN_TTL_SECONDS,))


async def guard_private_message(message) -> bool:
    if is_private_chat(message.chat):
        return False
    link = await dm_link(message.bot)
    await message.answer(PRIVATE_ONLY + (f"\n私聊入口：{link}" if link else ""))
    return True


async def guard_private_callback(callback) -> bool:
    if callback.message and is_private_chat(callback.message.chat):
        return False
    link = await dm_link(callback.bot)
    await callback.answer(PRIVATE_ONLY + (f"\n{link}" if link else ""), show_alert=True)
    return True


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 道行", callback_data="nav:me"),
         InlineKeyboardButton(text="🧘 闭关", callback_data="nav:cultivate")],
        [InlineKeyboardButton(text="⚔️ 历练", callback_data="nav:explore"),
         InlineKeyboardButton(text="🏯 秘境", callback_data="nav:dungeon")],
        [InlineKeyboardButton(text="💊 炼制", callback_data="nav:craft"),
         InlineKeyboardButton(text="📖 功法", callback_data="nav:skills")],
        [InlineKeyboardButton(text="🪙 商店", callback_data="nav:shop"),
         InlineKeyboardButton(text="🎒 储物袋", callback_data="nav:bag")],
        [InlineKeyboardButton(text="📜 悬赏", callback_data="nav:quest"),
         InlineKeyboardButton(text="🤝 师徒", callback_data="nav:master")],
        [InlineKeyboardButton(text="💞 道侣", callback_data="nav:partner"),
         InlineKeyboardButton(text="⛩️ 宗门", callback_data="nav:sect")],
        [InlineKeyboardButton(text="🧭 道途", callback_data="nav:path"),
         InlineKeyboardButton(text="🌌 飞升", callback_data="nav:ascension")],
        [InlineKeyboardButton(text="🗓️ 活动", callback_data="nav:weekly"),
         InlineKeyboardButton(text="🏷️ 坊市", callback_data="nav:market")],
        [InlineKeyboardButton(text="🔨 拍卖", callback_data="nav:auction"),
         InlineKeyboardButton(text="⚔️ 宗门战", callback_data="nav:sectwar")],
        [InlineKeyboardButton(text="📖 指南", callback_data="nav:help")],
    ])


def main_menu_return_button(text: str = "🏯 返回主菜单") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data="nav:menu")


def append_main_menu_return(
        rows: list[list[InlineKeyboardButton]],
        text: str = "🏯 返回主菜单") -> list[list[InlineKeyboardButton]]:
    rows.append([main_menu_return_button(text)])
    return rows


def button_grid(
        buttons: list[InlineKeyboardButton],
        width: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + width] for i in range(0, len(buttons), width)]


def main_menu_return_markup(text: str = "🏯 返回主菜单") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[main_menu_return_button(text)]])


def section_back_markup(
        text: str,
        callback_data: str,
        main_text: str = "🏯 主菜单") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=callback_data),
        InlineKeyboardButton(text=main_text, callback_data="nav:menu"),
    ]])


async def menu_with_breakthrough(user_id: int, can_advance: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_advance:
        rows.append([InlineKeyboardButton(
            text="⚡ 尝试突破",
            callback_data=await action_callback_data(user_id, "bt:do"))])
    append_main_menu_return(rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


LOW_HP_PCT = 0.30
LOW_MP_PCT = 0.25


def vitals_line(v: dict) -> str:
    """血蓝展示行；气血/法力偏低各追加软提示（#24，不硬拦出战）。"""
    line = f"❤️ 气血 {v['hp']}/{v['max_hp']}　🔵 法力 {v['mp']}/{v['max_mp']}"
    if v["max_hp"] > 0 and v["hp"] < v["max_hp"] * LOW_HP_PCT:
        line += "\n⚠️ 气血不足三成，凶险难料，宜先休整或服丹。"
    if v["max_mp"] > 0 and v["mp"] < v["max_mp"] * LOW_MP_PCT:
        line += "\n⚠️ 法力不足，战技恐难施展，宜回蓝后再战。"
    return line


def mp_starved_note(res: dict) -> str:
    """结算时若本场战斗法力偏低，补一句战技断档反馈（#24 P2）。无则空串。"""
    mx = res.get("max_mp", 0)
    low = min(res.get("battle_mp_before", mx), res.get("battle_mp_after", mx))
    if mx > 0 and low < mx * LOW_MP_PCT:
        return "📉 法力不济，战技多次断档转普攻，输出折损。"
    return ""


def battle_vitals_lines(res: dict) -> list:
    """结算血蓝展示（#24 P2）：先报本场战斗 出发→战斗末（解释胜负），
    若领取时当前状态与战斗末不同（嗑丹/回复/重伤地板）再补一行当前状态。"""
    lines = [
        f"⚔️ 气血 {res['battle_hp_before']}→{res['battle_hp_after']}/{res['max_hp']}"
        f"　🔵 法力 {res['battle_mp_before']}→{res['battle_mp_after']}/{res['max_mp']}"
    ]
    if res["hp_after"] != res["battle_hp_after"] or res["mp_after"] != res["battle_mp_after"]:
        lines.append(
            f"❤️ 当前 气血 {res['hp_after']}/{res['max_hp']}"
            f"　🔵 法力 {res['mp_after']}/{res['max_mp']}")
    note = mp_starved_note(res)
    if note:
        lines.append(note)
    return lines


def progress_bar(cur: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "▰" * width
    filled = max(0, min(width, int(width * cur / total)))
    return "▰" * filled + "▱" * (width - filled)
