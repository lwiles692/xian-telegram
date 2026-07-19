from __future__ import annotations

"""/skills —— 法宝与功法配置。"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.formatting import Bold, Text

from config import auction as auction_cfg
from config.equipment import QIHUN_KEY
from config.items import ITEMS, equipment_slot, format_bonus, item_name
from config import natal as NATAL
from config.skills import MIND_SLOT, skill_name
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             button_grid, consume_action_callback,
                             guard_private_callback, guard_private_message,
                             section_back_markup, show)
from services import character, equipment, natal as natal_service

router = Router()

SKILL_CATEGORIES = {
    "equipment": "法宝",
    "pages": "可领悟",
}


def _bonus_text(inst: dict) -> str:
    return format_bonus(character.enhanced_equipment_bonus(inst))


def _cost_text(cost: dict) -> str:
    parts = []
    if cost.get("stone"):
        parts.append(f"灵石 {cost['stone']}")
    parts.extend(f"{item_name(key)}×{qty}" for key, qty in cost.get("items", {}).items())
    return "、".join(parts) if parts else "无"


def _learnable_pages(inv: list[tuple[str, int]]) -> list[tuple[str, int, dict]]:
    pages = []
    for key, qty in inv:
        item = ITEMS.get(key, {})
        if item.get("type") == "page" and qty >= item.get("need", 999):
            pages.append((key, qty, item))
    return pages


def _equipment_mark(inst: dict) -> str:
    if inst.get("status") == auction_cfg.INSTANCE_STATUS_AUCTION:
        return "拍卖托管"
    if int(inst.get("natal_level") or 0) > 0:
        return f"本命Lv.{inst['natal_level']}"
    if int(inst.get("bound") or 0):
        return "已斩缚绑定"
    return "已装备" if inst["equipped_slot"] else "未装备"


def _equipment_list_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="↩️ 返回法宝列表",
        callback_data="skills:cat:equipment")


def _equipment_back_markup(instance_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    if instance_id is not None:
        rows.append([InlineKeyboardButton(
            text=f"↩️ 返回法宝 #{instance_id}",
            callback_data=f"skills:item:{instance_id}")])
    rows.append([_equipment_list_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_skills(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    mind = await character.get_mind_skill(user_id)
    skills = await character.get_skills(user_id)
    instances = await character.item_instances(user_id)
    inv = await character.inventory(user_id)
    learnable = _learnable_pages(inv)
    lines = [
        "📖 功法 / 法宝",
        "心法：" + (skill_name(mind) if mind else "无"),
        "战技栏：" + ("、".join(skill_name(s) for s in skills) if skills else "无"),
    ]
    qihun = dict(inv).get(QIHUN_KEY, 0)
    counts = []
    if instances:
        counts.append(f"法宝 {len(instances)}")
    if learnable:
        counts.append(f"可领悟 {len(learnable)}")
    lines.append(f"器魂：{qihun}")
    lines.append("操作：" + (" · ".join(counts) if counts else "暂无可操作项目"))
    entries = []
    if instances:
        entries.append(InlineKeyboardButton(text="法宝", callback_data="skills:cat:equipment"))
    if learnable:
        entries.append(InlineKeyboardButton(text="可领悟", callback_data="skills:cat:pages"))
    rows = button_grid(entries)
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def render_equipment_item(user_id: int, instance_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    instances = await character.item_instances(user_id)
    inst = next((item for item in instances if int(item["id"]) == instance_id), None)
    if not inst:
        return "未寻得此法宝。", _equipment_back_markup()

    inv = await character.inventory(user_id)
    qihun = dict(inv).get(QIHUN_KEY, 0)
    natal_id = int(char.natal_instance_id or 0)
    mark = _equipment_mark(inst)
    lvl = inst.get("enhance_level", 0)
    lvl_txt = f"+{lvl} " if lvl else ""
    lines = [
        "📖 法宝详情",
        f"#{inst['id']} {lvl_txt}{item_name(inst['base_key'])}",
        f"状态：{mark}",
        f"属性：{_bonus_text(inst)}",
        f"器魂 ×{qihun}",
    ]
    rows = []
    locked = inst.get("status") == auction_cfg.INSTANCE_STATUS_AUCTION
    if equipment_slot(inst["base_key"]) and not locked:
        rows.append([
            InlineKeyboardButton(
                text=f"强化#{inst['id']}",
                callback_data=await action_callback_data(
                    user_id, f"eq:enhance:{inst['id']}")),
            InlineKeyboardButton(
                text=f"重铸#{inst['id']}",
                callback_data=await action_callback_data(
                    user_id, f"eq:reforge:{inst['id']}")),
        ])
        if not inst["equipped_slot"]:
            rows.append([InlineKeyboardButton(
                text=f"分解#{inst['id']}",
                callback_data=await action_callback_data(
                    user_id, f"eq:decompose:{inst['id']}"))])

        natal_ops = []
        if int(inst.get("natal_level") or 0) > 0 and int(inst["id"]) == natal_id:
            if int(inst["natal_level"]) < NATAL.MAX_LEVEL:
                natal_ops.append(InlineKeyboardButton(
                    text=f"喂养#{inst['id']}",
                    callback_data=await action_callback_data(
                        user_id, f"natal:feed:{inst['id']}")))
            natal_ops.append(InlineKeyboardButton(
                text=f"斩缚#{inst['id']}",
                callback_data=await action_callback_data(
                    user_id, f"natal:unbind:{inst['id']}")))
        elif not natal_id and inst["tier"] in NATAL.ELIGIBLE_TIERS:
            if not int(inst.get("bound") or 0) and not int(inst.get("natal_level") or 0):
                natal_ops.append(InlineKeyboardButton(
                    text=f"认主#{inst['id']}",
                    callback_data=await action_callback_data(
                        user_id, f"natal:bind:{inst['id']}")))
        if natal_ops:
            rows.append(natal_ops)

    rows.append([_equipment_list_button()])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _equipment_sort_key(inst: dict):
    """法宝列表排序：已装备置顶，其余按编号升序。"""
    return (0 if inst["equipped_slot"] else 1, int(inst["id"]))


async def _render_equipment_list(user_id: int, instances: list[dict], qihun: int):
    """法宝列表：每件一块「粗体锚点行 + 属性次行」，已装备置顶。"""
    parts = [Bold("📖 法宝"), f"　器魂 ×{qihun} · 可用于强化/重铸"]
    rows = []
    for inst in sorted(instances, key=_equipment_sort_key):
        locked = inst.get("status") == auction_cfg.INSTANCE_STATUS_AUCTION
        lvl = inst.get("enhance_level", 0)
        lvl_txt = f" +{lvl}" if lvl else ""
        parts.append("\n\n")
        parts.append(Bold(
            f"#{inst['id']} {item_name(inst['base_key'])}{lvl_txt} · {_equipment_mark(inst)}"))
        parts.append(f"\n{_bonus_text(inst)}")
        if equipment_slot(inst["base_key"]) and not locked:
            action = (
                await action_callback_data(user_id, f"eq:unequip:{inst['id']}")
                if inst["equipped_slot"]
                else await action_callback_data(user_id, f"equip:{inst['id']}")
            )
            rows.append([
                InlineKeyboardButton(
                    text=f"{'卸下' if inst['equipped_slot'] else '装备'} #{inst['id']}",
                    callback_data=action),
                InlineKeyboardButton(
                    text=f"操作 #{inst['id']}",
                    callback_data=f"skills:item:{inst['id']}"),
            ])
    rows.append([InlineKeyboardButton(text="↩️ 返回功法", callback_data="nav:skills")])
    return Text(*parts), InlineKeyboardMarkup(inline_keyboard=rows)


async def render_skills_category(user_id: int, cat: str):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    if cat not in SKILL_CATEGORIES:
        return await render_skills(user_id)
    instances = await character.item_instances(user_id)
    inv = await character.inventory(user_id)
    if cat == "equipment":
        if not instances:
            return await render_skills(user_id)
        qihun = dict(inv).get(QIHUN_KEY, 0)
        return await _render_equipment_list(user_id, instances, qihun)
    lines = [f"📖 {SKILL_CATEGORIES[cat]}"]
    rows = []
    if cat == "pages":
        page_buttons = []
        for key, qty, item in _learnable_pages(inv):
            lines.append(f"{item_name(key)} {qty}/{item['need']}：{skill_name(item['skill'])}")
            page_buttons.append(InlineKeyboardButton(
                text=f"领悟 {skill_name(item['skill'])}",
                callback_data=await action_callback_data(user_id, f"learn:{key}")))
        rows += button_grid(page_buttons)
    if len(lines) == 1:
        return await render_skills(user_id)
    rows.append([InlineKeyboardButton(text="↩️ 返回功法", callback_data="nav:skills")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s == "ok" and "name" in res:
        return f"已装备 {res['name']}。"
    if s == "ok":
        slot_name = "心法栏" if res.get("slot") == MIND_SLOT else "战技栏"
        return f"已领悟 {skill_name(res['skill'])}，置入{slot_name}。"
    if s == "need_pages":
        return f"残页不足（需 {res['need']}，现有 {res['have']}）。"
    if s == "known":
        return f"{skill_name(res['skill'])} 已在战技栏中。"
    if s == "not_found":
        return "未寻得此法宝。"
    if s == "locked":
        return "此法宝正寄于拍卖行，暂不可装备。"
    return "天机不明，配置未变。"


@router.message(Command("skills"))
async def cmd_skills(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_skills(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:skills")
async def cb_skills(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_skills(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("skills:cat:"))
async def cb_skills_category(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    cat = callback.data.split(":", 2)[2]
    text, markup = await render_skills_category(callback.from_user.id, cat)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("skills:item:"))
async def cb_skills_item(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    try:
        instance_id = int(callback.data.rsplit(":", 1)[1])
    except (AttributeError, ValueError):
        instance_id = 0
    text, markup = await render_equipment_item(callback.from_user.id, instance_id)
    await show(callback, text, markup)
    await callback.answer()


def _eq_text(res: dict) -> str:
    s = res["status"]
    if s == "ok" and "unequipped" in res:
        return f"已卸下 {res['name']}。"
    if s == "ok" and "level" in res:
        c = res["cost"]
        return f"{res['name']} 强化至 +{res['level']}（耗灵石 {c['stone']}、器魂 {c.get(QIHUN_KEY, 0)}）。"
    if s == "ok" and "affixes" in res:
        aff = format_bonus(res["affixes"])
        c = res["cost"]
        return f"{res['name']} 重铸成功（耗灵石 {c['stone']}、器魂 {c.get(QIHUN_KEY, 0)}）。新词条：{aff}"
    if s == "ok" and "qihun" in res:
        return f"分解 {res['name']}，得器魂 ×{res['qihun']}。"
    if s == "max":
        return f"已至强化上限（+{res['level']}）。"
    if s == "equipped":
        return "装备中之物不可分解，请先卸下。"
    if s == "natal_bound":
        return "本命法宝已入神魂牵系，不可分解。"
    if s == "no_stone":
        return f"灵石不足（需 {res['need']}，余 {res['have']}）。"
    if s == "no_material":
        return f"{res['item']} 不足（需 {res['need']}，余 {res['have']}）。"
    if s == "not_equipment":
        return "此物不可如此炼制。"
    if s == "locked":
        return "此法宝正寄于拍卖行，暂不可炼制。"
    if s == "not_equipped":
        return "该法宝未装备，无需卸下。"
    if s == "not_found":
        return "未寻得此法宝。"
    return "炼制未成。"


def _natal_text(res: dict) -> str:
    s = res["status"]
    action = res.get("action")
    if s == "ok" and action == "bind":
        return f"{res['item']} 已祭为本命法宝（Lv.{res['level']}），耗 {_cost_text(res['cost'])}。"
    if s == "ok" and action == "feed":
        return f"{res['item']} 本命喂养至 Lv.{res['level']}，耗 {_cost_text(res['cost'])}。"
    if s == "ok" and action == "unbind":
        return f"已斩去 {res['item']} 的本命牵系，耗灵石 {res['cost']['stone']}。"
    if s == "realm_low":
        return "元婴期起方可祭炼本命法宝。"
    if s == "tier_low":
        return "仅宝阶、玄阶法宝可认主。"
    if s == "already_has_natal":
        return "已有本命法宝，需先斩缚。"
    if s == "natal_bound":
        return "此法宝已留本命旧痕，不可再祭。"
    if s == "no_natal":
        return "尚无本命法宝。"
    if s == "not_active":
        return "此物已非当前本命法宝，请刷新法宝页。"
    if s == "max":
        return f"本命法宝已至满级（Lv.{res['level']}）。"
    if s == "no_stone":
        return f"灵石不足（需 {res['need']}，余 {res['have']}）。"
    if s == "no_material":
        return f"{res['item']} 不足（需 {res['need']}，余 {res['have']}）。"
    if s == "locked":
        return "此法宝正寄于拍卖行，暂不可祭炼本命。"
    if s == "not_equipment":
        return "此物不可祭为本命法宝。"
    if s == "not_found":
        return "未寻得此法宝。"
    return "本命法宝事务未成。"


async def _eq_op(callback: CallbackQuery, prefix: str, fn):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith(prefix):
        return
    instance_id = int(action.rsplit(":", 1)[1])
    res = await fn(callback.from_user.id, instance_id)
    list_only = prefix == "eq:unequip:" or (
        prefix == "eq:decompose:" and res["status"] == "ok")
    markup = _equipment_back_markup(None if list_only else instance_id)
    await show(callback, _eq_text(res), markup)
    await callback.answer()


@router.callback_query(F.data.startswith("natal:"))
async def cb_natal_action(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("natal:"):
        return
    parts = action.split(":")
    op = parts[1] if len(parts) > 1 else ""
    instance_id = None
    try:
        instance_id = int(parts[2]) if len(parts) == 3 else None
        if op == "bind" and instance_id is not None:
            res = await natal_service.bind(callback.from_user.id, instance_id)
        elif op == "feed" and instance_id is not None:
            res = await natal_service.feed(callback.from_user.id, instance_id)
        elif op == "unbind" and instance_id is not None:
            res = await natal_service.unbind(callback.from_user.id, instance_id)
        else:
            res = {"status": "bad_request"}
    except ValueError:
        res = {"status": "bad_request"}
    res = {**res, "action": op}
    await show(callback, _natal_text(res), _equipment_back_markup(instance_id))
    await callback.answer()


@router.callback_query(F.data.startswith("eq:enhance:"))
async def cb_enhance(callback: CallbackQuery):
    await _eq_op(callback, "eq:enhance:", equipment.enhance)


@router.callback_query(F.data.startswith("eq:reforge:"))
async def cb_reforge(callback: CallbackQuery):
    await _eq_op(callback, "eq:reforge:", equipment.reforge)


@router.callback_query(F.data.startswith("eq:decompose:"))
async def cb_decompose(callback: CallbackQuery):
    await _eq_op(callback, "eq:decompose:", equipment.decompose)


@router.callback_query(F.data.startswith("eq:unequip:"))
async def cb_unequip(callback: CallbackQuery):
    await _eq_op(callback, "eq:unequip:", equipment.unequip)


@router.callback_query(F.data.startswith("equip:"))
async def cb_equip(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("equip:"):
        return
    res = await character.equip_instance(callback.from_user.id, int(action[6:]))
    await show(callback, _result_text(res), _equipment_back_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("learn:"))
async def cb_learn(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("learn:"):
        return
    res = await character.learn_skill_from_pages(callback.from_user.id, action[6:])
    await show(callback, _result_text(res), section_back_markup("↩️ 返回功法", "nav:skills"))
    await callback.answer()
