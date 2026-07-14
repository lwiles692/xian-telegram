"""/dungeon —— 秘境副本。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config.dungeons import DUNGEONS
from config.items import item_name
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             battle_report_page, battle_vitals_lines,
                             consume_action_callback,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show, vitals_line)
from services import character, dungeon
from services.combat import round_limit_label

router = Router()


async def render_dungeon(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    active = await dungeon.active_run(user_id)
    if active:
        rows = [[InlineKeyboardButton(
            text="领取结算" if active["status"] == "ready" else "刷新进度",
            callback_data=await action_callback_data(user_id, "dg:collect"))]]
        append_main_menu_return(rows)
        if active["status"] == "ready":
            text = f"🏯 {active['dungeon']} 已探索完成，可领取结算。"
        else:
            text = f"🏯 正在探索 {active['dungeon']}，约 {_minutes(active['remaining'])} 后完成。"
        return text, InlineKeyboardMarkup(inline_keyboard=rows)
    rows = []
    v = await character.vitals(char)
    lines = ["🏯 秘境", vitals_line(v),
             "各秘境每日限次不同，见下方条目。"]
    for key, d in DUNGEONS.items():
        state = "可入" if char.realm >= d["realm"] else "未解锁"
        limit = d.get("daily_limit", dungeon.DUNGEON_DAILY_LIMIT)
        lines.append(f"{d['name']}：{d['layers']} 层，精力 {d['stamina']}，每日 {limit} 次，约30分钟（{state}）")
        if char.realm >= d["realm"]:
            rows.append([InlineKeyboardButton(
                text=f"进入 {d['name']}",
                callback_data=await action_callback_data(user_id, f"dg:{key}"))])
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _active_markup(user_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text="领取 / 刷新秘境",
        callback_data=await action_callback_data(user_id, "dg:collect"))]]
    append_main_menu_return(rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _minutes(seconds: int) -> str:
    minutes = max(1, (seconds + 59) // 60)
    return f"{minutes} 分钟"


def _result_text(res: dict):
    s = res["status"]
    if s == "started":
        fee = res.get("entry_fee", 0)
        fee_txt = f"（入场费 {fee} 灵石）" if fee else ""
        return (
            f"🏯 已进入 {res['dungeon']}{fee_txt}，预计 {_minutes(res['seconds'])} 后完成。\n"
            f"⚡ 精力余 {res['stamina_left']}"
        )
    if s == "pending":
        return f"🏯 正在探索 {res['dungeon']}，约 {_minutes(res['remaining'])} 后完成。"
    if s == "ready":
        return f"🏯 {res['dungeon']} 已探索完成，请领取结算。"
    if s == "no_active":
        return "当前没有正在探索的秘境。"
    if s == "locked":
        return f"秘境云封雾锁，需至 {res['need']} 方可入内。"
    if s == "daily_done":
        return f"今日此秘境次数已用尽（{res.get('limit', dungeon.DUNGEON_DAILY_LIMIT)} 次），且待明日。"
    if s == "in_seclusion":
        return "道友仍在闭关，不可入秘境。"
    if s == "busy_explore":
        return "道友正在外历练，须归来后方可入秘境。"
    if s == "no_stamina":
        return f"精力不济（需 {res['need']}，余 {res['have']}）。"
    if s == "no_entry_fee":
        return f"入场费不足（需灵石 {res['need']}，余 {res['have']}）。"
    if s == "missing":
        return NEED_START
    if s == "bad_dungeon":
        return "查无此秘境。"
    rw = res["reward"]
    reward_lines = [f"🪙 {rw['stone']}", f"修为 +{rw['cult']}"]
    if rw.get("daohang"):
        reward_lines.append(f"道行 +{rw['daohang']}")
    if rw["drops"]:
        reward_lines.append("、".join(
            f"{item_name(k)}×{v}" for k, v in rw["drops"].items()))
    if rw["equipment"]:
        reward_lines.append("法宝：" + "、".join(rw["equipment"]))
    log = res["log"]
    if res["cleared"]:
        outcome = "秘境探索有所收获。"
    elif res.get("defeat_reason") == "round_limit":
        outcome = f"首层久战 {round_limit_label()}未决，按剩余气血比例判负，重伤而归（修为、装备无损）。"
        reward_lines = []
    else:
        outcome = "首层即力竭，重伤而归（修为、装备无损）。"
        reward_lines = []
    return battle_report_page(
        page="dungeon_result",
        title=f"🏯 {res['dungeon']}·深入 {res['cleared']}/{res['layers']} 层",
        outcome=outcome,
        log=log,
        rewards=reward_lines if res["cleared"] else [],
        status=battle_vitals_lines(res) + [f"⚡ 精力余 {res['stamina_left']}"],
    )


@router.message(Command("dungeon"))
async def cmd_dungeon(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_dungeon(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:dungeon")
async def cb_dungeon(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_dungeon(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("dg:"))
async def cb_dungeon_run(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("dg:"):
        return
    if action == "dg:collect":
        res = await dungeon.collect(callback.from_user.id)
    else:
        res = await dungeon.start(callback.from_user.id, action[3:])
    markup = await _active_markup(callback.from_user.id) if res["status"] in {
        "started", "pending", "ready",
    } else section_back_markup("↩️ 返回秘境", "nav:dungeon")
    await show(callback, _result_text(res), markup)
    await callback.answer()
