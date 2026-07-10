from __future__ import annotations

"""/boss —— 群内世界 Boss。"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.common import action_callback_data, consume_action_callback, is_private_chat, show
from config.bosses import WORLD_BOSSES, canonical_boss_key
from services import world_boss

router = Router()


async def _markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚔️ 挑战 Boss",
            callback_data=await action_callback_data(None, "boss:hit")),
         InlineKeyboardButton(text="🐲 查看战况", callback_data="boss:status")]
    ])


def _leader_lines(rows: list) -> list:
    if not rows:
        return ["暂无伤害记录。"]
    return [
        f"{idx}. {row['username'] or row['user_id']}：{row['damage']}"
        for idx, row in enumerate(rows, 1)
    ]


def _status_text(res: dict) -> str:
    if res["status"] == "none":
        return "今日暂无世界 Boss。发送 /boss 可唤出群内强敌。"
    boss = res["boss"]
    cfg = WORLD_BOSSES[canonical_boss_key(boss["boss_key"])]
    pct = boss["remaining_hp"] / boss["total_hp"] if boss["total_hp"] else 0
    bar = "▰" * int(pct * 10) + "▱" * (10 - int(pct * 10))
    state = "已伏诛" if res["status"] == "defeated" else "已遁去" if res["status"] == "expired" else "鏖战中"
    return "\n".join([
        f"🐲 世界 Boss：{cfg['name']}（{state}）",
        f"气血：{boss['remaining_hp']}/{boss['total_hp']} {bar}",
        "—— 伤害榜 ——",
        *_leader_lines(res["leaderboard"]),
    ])


def _challenge_text(res: dict) -> str:
    s = res["status"]
    if s == "ok":
        lines = [
            f"🐲 {res['boss_name']}",
            f"本次造成伤害 {res['damage']}，余血 {res['remaining_hp']}/{res['total_hp']}。",
            "—— 伤害榜 ——",
            *_leader_lines(res["leaderboard"]),
        ]
        if res.get("daohang"):
            lines.append(f"道行 +{res['daohang']}。")
        if res.get("partner_combo"):
            lines.append(res["partner_combo"])
        if res["defeated"]:
            lines.append(world_boss.reward_text(res["rewards"]))
        return "\n".join(line for line in lines if line)
    if s == "no_stamina":
        return f"精力不济（需 {res['need']}，余 {res['have']}）。"
    if s == "in_seclusion":
        return "道友闭关中，不可挑战世界 Boss。"
    if s == "expired":
        return "Boss 已遁去，待下次刷新。"
    return "Boss 战未成。"


@router.message(Command("boss"))
async def cmd_boss(message: Message):
    if is_private_chat(message.chat):
        await message.answer("世界 Boss 请在群中合击。")
        return
    await world_boss.remember_chat(message.chat.id, message.chat.title)
    await world_boss.remember_cultivator(message.chat.id, message.from_user.id)
    await world_boss.ensure_active(message.chat.id)
    res = await world_boss.status(message.chat.id)
    markup = await _markup()
    if res["status"] != "none" and res["boss"].get("message_id"):
        try:
            await message.bot.edit_message_text(
                text=_status_text(res), chat_id=message.chat.id, message_id=res["boss"]["message_id"],
                reply_markup=markup)
            return
        except Exception:
            pass
    sent = await message.answer(_status_text(res), reply_markup=markup)
    if res["status"] != "none":
        await world_boss.remember_message(res["boss"]["id"], sent.message_id)


@router.callback_query(F.data == "boss:status")
async def cb_boss_status(callback: CallbackQuery):
    res = await world_boss.status(callback.message.chat.id)
    await show(callback, _status_text(res), await _markup())
    if res["status"] != "none":
        await world_boss.remember_message(res["boss"]["id"], callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("boss:hit:"))
async def cb_boss_hit(callback: CallbackQuery):
    if await consume_action_callback(callback) != "boss:hit":
        return
    res = await world_boss.challenge(callback.message.chat.id, callback.from_user.id)
    await show(callback, _challenge_text(res), await _markup())
    if res["status"] == "ok":
        await world_boss.remember_message(res["boss_id"], callback.message.message_id)
    await callback.answer()
