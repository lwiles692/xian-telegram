"""/explore —— 选图历练 + 战斗结算。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from config import realms as R
from config.items import item_name
from config.maps import lower_maps, maps_at_realm
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             battle_vitals_lines, consume_action_callback,
                             battle_report_page,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show, vitals_line)
from services import character
from services import explore as explore_service
from services.combat import round_limit_label

router = Router()


async def _map_button(user_id: int, key: str, m: dict) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=f"{m['name']}·{m['difficulty']}（精力{m['stamina']}）",
        callback_data=await action_callback_data(user_id, f"ex:{key}"))


async def _map_row(user_id: int, key: str, m: dict, realm: int) -> list[InlineKeyboardButton]:
    row = [await _map_button(user_id, key, m)]
    if realm == m["realm"] and await explore_service.can_sweep(user_id, key):
        row.append(InlineKeyboardButton(
            text="扫荡",
            callback_data=await action_callback_data(user_id, f"ex:sweep:{key}")))
    return row


async def render_menu(user_id: int, show_lower: bool = False):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    active = await explore_service.active_run(user_id)
    if active:
        rows = [[InlineKeyboardButton(
            text="领取结算" if active["status"] == "ready" else "刷新进度",
            callback_data=await action_callback_data(user_id, "ex:collect"))]]
        append_main_menu_return(rows)
        if active["status"] == "ready":
            text = f"⚔️ {active['map']} 历练已完成，可领取结算。"
        else:
            text = f"⚔️ 正在 {active['map']} 历练，约 {_minutes(active['remaining'])} 后归来。"
        return text, InlineKeyboardMarkup(inline_keyboard=rows)
    welfare = await character.sect_welfare(user_id)
    cap = R.STAMINA_CAP[char.realm] + welfare["stamina_bonus"]
    rows = []
    if show_lower:
        for key, m in lower_maps(char.realm):
            rows.append(await _map_row(user_id, key, m, char.realm))
        rows.append([InlineKeyboardButton(text="⬅️ 返回当前境界", callback_data="nav:explore")])
        header = "📜 低阶历练（刷低阶材料 / 补突破资源）："
    else:
        for key, m in maps_at_realm(char.realm):
            rows.append(await _map_row(user_id, key, m, char.realm))
        if lower_maps(char.realm):
            rows.append([InlineKeyboardButton(
                text="📜 低阶历练", callback_data="nav:explore:lower")])
        header = "本境界三处历练之地（易 / 中 / 难），择一斩妖夺宝："
    append_main_menu_return(rows)
    v = await character.vitals(char)
    text = f"⚔️ 历练\n⚡ 精力 {char.stamina}/{cap}\n{vitals_line(v)}\n{header}"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _after_markup(user_id: int, map_key: str) -> InlineKeyboardMarkup:
    first = [InlineKeyboardButton(
        text="🔁 再历练一次",
        callback_data=await action_callback_data(user_id, f"ex:{map_key}"))]
    if await explore_service.can_sweep(user_id, map_key):
        first.append(InlineKeyboardButton(
            text="扫荡",
            callback_data=await action_callback_data(user_id, f"ex:sweep:{map_key}")))
    first.append(InlineKeyboardButton(text="⚔️ 换地图", callback_data="nav:explore"))
    rows = [first]
    append_main_menu_return(rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _active_markup(user_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text="领取 / 刷新历练",
        callback_data=await action_callback_data(user_id, "ex:collect"))]]
    append_main_menu_return(rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _event_markup(user_id: int, res: dict) -> InlineKeyboardMarkup:
    rows = []
    for choice in res.get("choices", []):
        rows.append([InlineKeyboardButton(
            text=choice["label"],
            callback_data=await action_callback_data(user_id, f"ex:event:{choice['key']}"))])
    append_main_menu_return(rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _minutes(seconds: int) -> str:
    minutes = max(1, (seconds + 59) // 60)
    return f"{minutes} 分钟"


def _result_text(res: dict):
    s = res["status"]
    if s == "started":
        return (
            f"⚔️ 已前往 {res['map']} 历练，预计 {_minutes(res['seconds'])} 后归来。\n"
            f"⚡ 精力余 {res['stamina_left']}"
        )
    if s == "event":
        return f"✨ 奇遇：{res['title']}\n{res['text']}"
    if s == "pending":
        return f"⚔️ 正在 {res['map']} 历练，约 {_minutes(res['remaining'])} 后归来。"
    if s == "ready":
        return f"⚔️ {res['map']} 历练已完成，请领取结算。"
    if s == "no_active":
        return "当前没有正在进行的历练。"
    if s == "locked":
        return f"此地凶险，需修为至 {res['need']} 方可踏足。"
    if s == "in_seclusion":
        return "道友尚在闭关，当前操作不可执行。"
    if s == "busy_explore":
        return "已有一场历练未结，须先领取结算。"
    if s == "busy_dungeon":
        return "道友正在秘境之中，须出秘境后方可外出历练。"
    if s == "no_stamina":
        return f"精力不济（需 {res['need']}，余 {res['have']}），且去闭关歇息。"
    if s == "sweep_locked":
        return f"此地尚未稳定通关，需连续胜利 {res['need']} 次方可扫荡。"
    if s == "bad_choice":
        return "此奇遇选项已散入云烟，请刷新后再试。"
    if s == "no_event":
        return "当前没有待处理的奇遇。"
    if s == "missing":
        return NEED_START
    if s == "bad_map":
        return "查无此地。"
    log = res["log"]
    shown = log if len(log) <= 11 else (log[:10] + ["……", log[-1]])
    prefix = []
    if res.get("sweep"):
        prefix.append(f"⚡ 扫荡 {res['map']}。")
    if res["is_boss"]:
        prefix.append("🐲 妖王现身！")
    outcome_parts = prefix
    if res["win"]:
        rw = res["reward"]
        reward_lines = [f"🪙 {rw['stone']}", f"修为 +{rw['cult']}"]
        if rw.get("daohang"):
            reward_lines.append(f"道行 +{rw['daohang']}")
        if rw["drops"]:
            reward_lines.append("、".join(
                f"{item_name(k)}×{v}" for k, v in rw["drops"].items()))
        outcome_parts.append("历练大捷。")
    elif res.get("defeat_reason") == "round_limit":
        reward_lines = []
        outcome_parts.append(
            f"久战 {round_limit_label()}未决，按剩余气血比例判负，重伤而归（修为、装备无损，养息后再来）。")
    else:
        reward_lines = []
        outcome_parts.append("道友力竭，重伤而归（修为、装备无损，养息后再来）。")
    title = f"⚔️ {res['map']}·{'大捷' if res['win'] else '重伤而归'}"
    return battle_report_page(
        page="explore_result",
        title=title,
        outcome="\n".join(outcome_parts),
        log=shown,
        rewards=reward_lines,
        status=battle_vitals_lines(res) + [f"⚡ 精力余 {res['stamina_left']}"],
    )


@router.message(Command("explore"))
async def cmd_explore(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_menu(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:explore")
async def cb_explore_menu(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_menu(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data == "nav:explore:lower")
async def cb_explore_lower(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_menu(callback.from_user.id, show_lower=True)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("ex:"))
async def cb_explore_go(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("ex:"):
        return
    if action == "ex:collect":
        res = await explore_service.collect(callback.from_user.id)
    elif action.startswith("ex:sweep:"):
        res = await explore_service.sweep(callback.from_user.id, action.split(":", 2)[2])
    elif action.startswith("ex:event:"):
        res = await explore_service.choose_event(callback.from_user.id, action.rsplit(":", 1)[1])
    else:
        res = await explore_service.start(callback.from_user.id, action[3:])
    if res["status"] == "ok":
        markup = await _after_markup(callback.from_user.id, res["map_key"])
    elif res["status"] == "event":
        markup = await _event_markup(callback.from_user.id, res)
    elif res["status"] in {"started", "pending", "ready"}:
        markup = await _active_markup(callback.from_user.id)
    else:
        markup = section_back_markup("↩️ 返回历练", "nav:explore")
    await show(callback, _result_text(res), markup)
    await callback.answer()
