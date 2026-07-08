"""/cultivate —— 闭关 / 出关；以及突破回调 bt:do。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config.events import TRIBULATION_ACTIONS
from handlers.common import (NEED_START, guard_private_callback, guard_private_message,
                             action_callback_data, append_main_menu_return,
                             consume_action_callback, menu_with_breakthrough,
                             section_back_markup, show)
from services import breakthrough, character, cultivation

router = Router()


async def do_cultivate(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    if char.seclusion_at:
        res = await cultivation.collect(user_id)
        if res["status"] != "collected":
            return "闭关状态已变，请稍后再试。", section_back_markup("↩️ 返回闭关", "nav:cultivate")
        lines = [f"🧘 出关！闭关 {res['minutes']} 分钟，修为精进 +{res['gained']}。",
                 f"修为 {res['cultivation']}/{res['cost']}"]
        if res["can_advance"]:
            lines.append("✨ 修为已足，可尝试突破！")
        return "\n".join(lines), await menu_with_breakthrough(user_id, res["can_advance"])
    res = await cultivation.start(user_id)
    if res["status"] == "busy_explore":
        return "道友正在外历练，须归来后方可闭关。", section_back_markup("↩️ 返回闭关", "nav:cultivate")
    if res["status"] == "busy_dungeon":
        return "道友正在秘境之中，须出秘境后方可闭关。", section_back_markup("↩️ 返回闭关", "nav:cultivate")
    text = ("🧘 道友盘膝而坐，敛息凝神，开始闭关参悟……\n"
            "（修为随时间累积，离线上限 12 时辰。再用一次 /cultivate 或点「闭关」即出关收功。）")
    return text, section_back_markup("↩️ 返回闭关", "nav:cultivate")


async def render_cultivate(user_id: int):
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    if char.seclusion_at:
        text = "🧘 道友正在闭关。若要收功出关，请点下方按钮。"
        button = "出关收功"
    else:
        text = "🧘 洞府清净，可入定闭关，离线积攒修为。"
        button = "开始闭关"
    rows = [[InlineKeyboardButton(
        text=button,
        callback_data=await action_callback_data(user_id, "cult:toggle"))]]
    append_main_menu_return(rows)
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _bt_text(res: dict) -> str:
    s = res["status"]
    if s == "need_cult":
        return f"修为尚浅，还差 {res['need']} 方可冲关。且去闭关或历练。"
    if s == "in_seclusion":
        return "道友仍在闭关，不宜分心冲关。且先出关收功。"
    if s == "missing":
        return NEED_START
    if s == "at_cap":
        return "道友已臻当前大道顶点，修为封顶；后续溢出将转为道行与飞升点，可继续打磨根基。"
    if s == "need_pill":
        pill = res["pill"]
        hint = ""
        if pill == "化神丹":
            # spec T0.8：神魂劫缺丹需指明来源，避免玩家卡关无解。
            hint = "（可往天外古墟、天魔古原寻丹，或集化神丹残方/太虚天门得方炼制。）"
        elif pill == "炼虚丹":
            # spec-v3 §3.4：炼虚首破来源必须落在化神可及内容，缺丹时直接指路。
            hint = "（可往天外古墟、太虚天门、化神世界 Boss 寻残方，或得炼虚丹方后炼制。）"
        return f"大境界突破需「{pill}」护道，道友尚缺此物。{hint}"
    if s == "tribulation_choice":
        tail = "\n".join(res.get("last_log") or res.get("tribulation_log") or [])
        trial = "神魂劫" if res.get("target_realm") == 4 else "天劫"
        fall = "魔念翻涌" if res.get("target_realm") == 4 else "雷将落"
        prefix = f"⚡ {trial}未尽，第 {res['thunder_index']}/{res.get('total', 3)} 段{fall}。"
        hp = f"\n当前气血：{res['hp']}" if res.get("hp") is not None else ""
        return "\n".join(line for line in [prefix + hp, _rate_text(res), tail, "请选择应对。"] if line)
    if s == "need_item":
        return f"缺少「{res['item']}」，此法暂不可用。"
    if s == "bad_action":
        return "此应劫之法不可用。"
    if s == "no_tribulation":
        return "当前没有进行中的天劫。"
    if s == "small_success":
        return f"📈 水到渠成，道友晋入 {res['label']}！"
    if s == "big_success":
        tail = "\n" + "\n".join(res.get("tribulation_log", [])) if res.get("tribulation_log") else ""
        rate = f"\n{_rate_text(res)}" if _rate_text(res) else ""
        if res["tribulation"]:
            trial = "神魂劫" if "神魂劫" in tail else "天劫"
            if trial == "神魂劫":
                return f"🌀 神魂劫已尽，心魔归寂——道友破妄凝神，臻至 {res['label']}！{rate}{tail}"
            return f"⚡ 天劫加身，雷光淬体——道友力扛三道天雷，破境而出，臻至 {res['label']}！{rate}{tail}"
        return f"✨ 灵气灌顶，道友冲破桎梏，迈入 {res['label']}！{rate}"
    if s == "big_fail":
        tail = "\n" + "\n".join(res.get("tribulation_log", [])) if res.get("tribulation_log") else ""
        rate = f"\n{_rate_text(res)}" if _rate_text(res) else ""
        if res["tribulation"]:
            head = "🌀 神魂劫凶险" if "神魂劫" in tail else "⚡ 天劫凶猛"
        else:
            head = "✗ 冲关受阻"
        return (
            f"{head}，道友未能破境，道基不稳（修为 −{res['loss']}，"
            f"法身六维暂降），所幸未曾跌境。来日再战。{rate}{tail}"
        )
    return "天机紊乱，突破未果。"


def _rate_text(res: dict) -> str:
    if "rate" not in res:
        return ""
    rate = int(round(float(res["rate"]) * 100))
    guarantee = float(res.get("guarantee_bonus") or 0.0)
    if guarantee > 0:
        bonus = int(round(guarantee * 100))
        return f"本次破境成功率：{rate}%（保底+{bonus}%）。"
    return f"本次破境成功率：{rate}%。"


async def _bt_markup(user_id: int, res: dict):
    if res["status"] != "tribulation_choice":
        # 突破入口在道行页；突破结果返回道行面板，便于继续查看进度。
        return section_back_markup("↩️ 返回道行", "nav:me")
    rows = []
    for choice in res.get("choices", []):
        rows.append([InlineKeyboardButton(
            text=choice["label"],
            callback_data=await action_callback_data(user_id, f"bt:trib:{choice['key']}"))])
    append_main_menu_return(rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("cultivate"))
async def cmd_cultivate(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await do_cultivate(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:cultivate")
async def cb_cultivate(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_cultivate(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cult:toggle:"))
async def cb_cultivate_toggle(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    if await consume_action_callback(callback) != "cult:toggle":
        return
    text, markup = await do_cultivate(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("bt:do:"))
async def cb_breakthrough(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    if await consume_action_callback(callback) != "bt:do":
        return
    res = await breakthrough.try_advance(callback.from_user.id)
    await show(callback, _bt_text(res), await _bt_markup(callback.from_user.id, res))
    await callback.answer()


@router.callback_query(F.data.startswith("bt:trib:"))
async def cb_tribulation(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("bt:trib:"):
        return
    res = await breakthrough.choose_tribulation_action(
        callback.from_user.id, action.rsplit(":", 1)[1])
    await show(callback, _bt_text(res), await _bt_markup(callback.from_user.id, res))
    await callback.answer()
