from __future__ import annotations

"""/me —— 角色面板。"""

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.formatting import Bold, Text

from bot.presentation import answer

from config import realms as R
from config.items import item_name
from config.skills import skill_name
from handlers.common import (NEED_START, guard_private_callback, guard_private_message,
                             menu_with_breakthrough, progress_bar, show)
from services import bonds as bonds_service, character, quests

router = Router()


async def render_me(user_id: int) -> tuple[str | Text, InlineKeyboardMarkup | None]:
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    equipped = await character.equipped_items(user_id)
    st = await character.stats(char, equipped=equipped)
    v = await character.vitals(char, stat_block=st)
    cost = R.advance_cost(char.realm, char.stage)
    welfare = await character.sect_welfare(user_id)
    cap = R.STAMINA_CAP[char.realm] + welfare["stamina_bonus"]
    mind = await character.get_mind_skill(user_id)
    skills = await character.get_skills(user_id)
    weapon_key = character.current_weapon_key(char, equipped)
    overflow = await character.overflow_status(user_id)
    seclusion = "（闭关中 🧘）" if char.seclusion_at else ""
    status_parts: list[str] = []
    partner = await bonds_service.partner_overview(user_id)
    if partner["status"] == "ok" and partner["active_partner"]:
        active = partner["active_partner"]
        status_parts.append(f"\n💞 道侣：{active['partner_name']}（{partner['title']}）")
    if overflow.get("active"):
        status_parts.append(f"\n🌌 溢出分流：{overflow['label']}")
    if int(char.debuff_json.get("unstable_until", 0)) > int(time.time()):
        status_parts.append("\n⚠️ 道基不稳：法身六维暂降。")
    ach = (await quests.list_status(user_id))["achievements"]
    if ach:
        shown = "、".join(quests.achievement_name(row["key"]) for row in ach[:3])
        status_parts.append(f"\n🏅 成就：{shown}")
    if not status_parts:
        status_parts.append("\n暂无异状")
    content = Text(
        Bold(f"📜 {char.spirit_root} · 根骨 {char.root_bone}"),
        "\n", Bold("境界与资源"),
        f"\n境界：{R.realm_label(char.realm, char.stage)} {seclusion}",
        f"\n修为：{char.cultivation}/{cost}  {progress_bar(char.cultivation, cost)}",
        f"\n🪙 灵石 {char.spirit_stone}　⚡ 精力 {char.stamina}/{cap}",
        "\n\n", Bold("法身六维"),
        f"\n气血 {v['hp']}/{v['max_hp']}　法力 {v['mp']}/{v['max_mp']}",
        f"\n攻击 {st['atk']}　防御 {st['df']}　身法 {st['spd']}　暴击 {st['crit']}",
        "\n\n", Bold("法宝功法"),
        f"\n⚔️ 法宝：{item_name(weapon_key)}",
        "\n📖 心法：", skill_name(mind) if mind else "无",
        "\n📖 战技：", "、".join(skill_name(s) for s in skills) if skills else "无",
        "\n\n", Bold("关系与状态"),
        *status_parts,
    )
    can_advance = char.cultivation >= cost and not char.seclusion_at
    return content, await menu_with_breakthrough(user_id, can_advance)


@router.message(Command("me"))
async def cmd_me(message: Message):
    if await guard_private_message(message):
        return
    content, markup = await render_me(message.from_user.id)
    await answer(message, content, markup)


@router.callback_query(F.data == "nav:me")
async def cb_me(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_me(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()
