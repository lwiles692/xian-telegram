"""/pvp —— 群内切磋 / 天梯。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.common import (NEED_START, action_callback_data,
                             battle_report_page, consume_action_callback,
                             is_private_chat, show)
from services import pvp, world_boss

router = Router()


def _name(user) -> str:
    return user.username or user.full_name or str(user.id)


def _outcome_text(res: dict) -> str:
    reason = res.get("finish_reason")
    if reason == "round_limit":
        return ("久战未决，斗法台判你残余气机更盛" if res["win"]
                else "久战未决，斗法台判对手残余气机更盛")
    if reason == "double_down":
        return ("双双力竭，斗法台判你气机更盛" if res["win"]
                else "双双力竭，斗法台判对手气机更盛")
    return "技高一筹" if res["win"] else "惜败半招"


def _text(res: dict, opponent_name: str = "对手"):
    s = res["status"]
    if s == "ok":
        attacker = res.get("attacker_name", "道友")
        defender = res.get("defender_name", opponent_name)
        shown = res["log"] if len(res["log"]) <= 8 else (res["log"][:7] + ["……", res["log"][-1]])
        rep_txt = (f"声望 +{res['reputation_gain']}" if res.get("reputation_counted", True)
                   else "声望 +0（今日已与此对手切磋）")
        tier_txt = f"（{res['tier']}）" if res.get("tier") else ""
        return battle_report_page(
            page="pvp_result",
            title=f"⚔️ 切磋：{attacker} vs {defender}",
            outcome=_outcome_text(res),
            log=shown,
            rewards=[],
            status=[
                f"天梯积分 {res['rating_delta']:+d}{tier_txt}",
                f"{rep_txt}。周榜奖池按声望排名结算。",
            ],
        )
    if s == "no_opponent":
        return "暂未寻得合适对手。可让另一位道友先 /start。"
    if s == "daily_limit":
        return f"今日切磋已满 {res['limit']} 次。"
    if s == "realm_gap":
        return "境界相差过大，此战不合天梯规矩。"
    if s == "missing":
        return NEED_START
    if s == "self":
        return "与己切磋，剑意无所落处。"
    return "切磋未成。"


def _preview_text(attacker_name: str, opponent_name: str) -> str:
    return "\n".join([
        f"⚔️ 切磋邀战：{attacker_name} vs {opponent_name}",
        "此战只影响天梯积分与声望，不掉资源。",
        "斗法台有禁制压阵，疗伤、汲血与护盾皆受压，久战按残余气机裁定。",
        "确认后即刻自动结算。",
    ])


async def _confirm_markup(user_id: int, defender_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚔️ 确认切磋",
            callback_data=await action_callback_data(user_id, f"pvp:duel:{defender_id}"))]
    ])


@router.message(Command("pvp"))
async def cmd_pvp(message: Message):
    if is_private_chat(message.chat):
        await message.answer("切磋与天梯请在群中进行。")
        return
    await world_boss.remember_chat(message.chat.id, message.chat.title)
    await world_boss.remember_cultivator(message.chat.id, message.from_user.id)
    defender_id = None
    opponent_name = "随机对手"
    if message.reply_to_message and message.reply_to_message.from_user:
        opponent = message.reply_to_message.from_user
        defender_id = opponent.id
        opponent_name = _name(opponent)
        await world_boss.remember_cultivator(message.chat.id, defender_id)
    else:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            found = await pvp.opponent_from_arg(parts[1])
            if found["status"] != "ok":
                await message.answer("未寻得指定对手。可用 /pvp 随机匹配、回复某人 /pvp，或 /pvp @道号、/pvp #1。")
                return
            defender_id = found["user_id"]
            opponent_name = str(found["name"])
    preview = await pvp.preview_duel(message.from_user.id, defender_id)
    if preview["status"] != "ok":
        await message.answer(_text(preview, opponent_name))
        return
    await message.answer(
        _preview_text(_name(message.from_user),
                      opponent_name if defender_id else preview["name"]),
        reply_markup=await _confirm_markup(message.from_user.id, preview["defender_id"]))


@router.callback_query(F.data.startswith("pvp:duel:"))
async def cb_pvp_confirm(callback: CallbackQuery):
    action = await consume_action_callback(callback)
    if not action or not action.startswith("pvp:duel:"):
        return
    if callback.message and not is_private_chat(callback.message.chat):
        await world_boss.remember_cultivator(callback.message.chat.id, callback.from_user.id)
    defender_id = int(action.rsplit(":", 1)[1])
    res = await pvp.duel(callback.from_user.id, defender_id,
                         attacker_name=_name(callback.from_user))
    await show(callback, _text(res), None)
    await callback.answer()
