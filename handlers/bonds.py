from __future__ import annotations

"""/master / /partner —— 师徒 / 道侣。"""

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import bonds as BONDS
from config.items import item_name
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             button_grid, consume_action_callback,
                             guard_private_callback, guard_private_message,
                             is_private_chat, section_back_markup, show)
from services import bonds as bonds_service, character, communion

router = Router()

_MASTER_CALLBACK_OPS = frozenset({
    "create", "confirm", "decline", "dissolve", "transfer", "graduate",
})


def _is_master_callback(data: str | None) -> bool:
    if not data or not data.startswith("bond:"):
        return False
    action = data.rsplit(":", 1)[0]
    parts = action.split(":")
    return len(parts) > 1 and parts[1] in _MASTER_CALLBACK_OPS


def _fmt_time(ts: int | None) -> str:
    if not ts:
        return "未知"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))


async def render_master(user_id: int):
    state = await bonds_service.mentor_overview(user_id)
    if state["status"] == "missing":
        return NEED_START, None
    lines = ["🤝 师徒"]
    rows = []
    mentor = state["active_mentor"]
    if mentor:
        lines.append(
            f"师父：{mentor['mentor_name']}（活跃 {mentor['active_days']}/"
            f"{BONDS.GRADUATION_ACTIVE_DAYS_REQUIRED} 日）")
        rows.append([
            InlineKeyboardButton(
                text="🎓 申请出师",
                callback_data=await action_callback_data(
                    user_id, f"bond:graduate:{mentor['bond_id']}")),
            InlineKeyboardButton(
                text="解除师徒",
                callback_data=await action_callback_data(
                    user_id, f"bond:dissolve:{mentor['bond_id']}")),
        ])
    else:
        lines.append("师父：暂无")
    disciples = state["active_disciples"]
    if disciples:
        lines.append("门下弟子：")
        for item in disciples:
            lines.append(
                f"- {item['disciple_name']} · 活跃 "
                f"{item['active_days']}/{BONDS.GRADUATION_ACTIVE_DAYS_REQUIRED} 日")
        buttons = []
        for item in disciples:
            buttons.append(InlineKeyboardButton(
                text=f"传功 {item['disciple_name']}",
                callback_data=await action_callback_data(
                    user_id, f"bond:transfer:{item['disciple_id']}")))
            buttons.append(InlineKeyboardButton(
                text=f"出师 {item['disciple_name']}",
                callback_data=await action_callback_data(
                    user_id, f"bond:graduate:{item['bond_id']}")))
            buttons.append(InlineKeyboardButton(
                text=f"解除 {item['disciple_name']}",
                callback_data=await action_callback_data(
                    user_id, f"bond:dissolve:{item['bond_id']}")))
        rows.extend(button_grid(buttons))
    else:
        lines.append("门下弟子：暂无")
    if state["pending_incoming"]:
        lines.append("待你确认：")
        for item in state["pending_incoming"]:
            other = item["mentor_name"] if item["disciple_id"] == user_id else item["disciple_name"]
            lines.append(f"- {other} 的拜师帖（至 {_fmt_time(item['expires_at'])}）")
            rows.append([
                InlineKeyboardButton(
                    text=f"同意 {other}",
                    callback_data=await action_callback_data(
                        user_id, f"bond:confirm:{item['bond_id']}")),
                InlineKeyboardButton(
                    text=f"婉拒 {other}",
                    callback_data=await action_callback_data(
                        user_id, f"bond:decline:{item['bond_id']}")),
            ])
    if state["pending_outgoing"]:
        lines.append("已递出的拜师帖：")
        for item in state["pending_outgoing"]:
            other = item["mentor_name"] if item["disciple_id"] == user_id else item["disciple_name"]
            lines.append(f"- {other} 待确认（至 {_fmt_time(item['expires_at'])}）")
    titles = [row["title"] for row in state["titles"]]
    if titles:
        lines.append("桃李称号：" + "、".join(titles))
    if state["cooldown_until"]:
        lines.append(f"冷却至：{_fmt_time(state['cooldown_until'])}")
    lines.append("用法：/master 拜师 对方ID，或 /master 收徒 对方ID。")
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def render_partner(user_id: int):
    state = await bonds_service.partner_overview(user_id)
    if state["status"] == "missing":
        return NEED_START, None
    lines = ["💞 道侣"]
    rows = []
    partner = state["active_partner"]
    if partner:
        lines.append(f"道侣：{partner['partner_name']}（{state['title']}）")
        lines.append("双修：闭关时辰相叠，重叠部分额外折入少量修为。")
        gift_items = state["gift_items"]
        if gift_items:
            lines.append("今日可赠：" + "、".join(
                f"{item_name(item['item_key'])}×{item['qty']}" for item in gift_items))
            buttons = [
                InlineKeyboardButton(
                    text=f"赠 {item_name(item['item_key'])}",
                    callback_data=await action_callback_data(
                        user_id, f"bond:pgift:{item['item_key']}"))
                for item in gift_items[:6]
            ]
            rows.extend(button_grid(buttons))
        else:
            lines.append("今日可赠：暂无绑定白名单物品。")
        await _append_communion_rows(lines, rows, user_id, partner, state["open_communion"])
        rows.append([
            InlineKeyboardButton(
                text="解除道侣",
                callback_data=await action_callback_data(
                    user_id, f"bond:pdissolve:{partner['bond_id']}")),
        ])
    else:
        lines.append("道侣：暂无")
        lines.append("用法：/partner 结契 对方ID。双方需金丹期以上，确认时消耗 1 枚绑定同心结。")
    if state["pending_incoming"]:
        lines.append("待你确认的结契帖：")
        for item in state["pending_incoming"]:
            lines.append(f"- {item['partner_name']} 邀你结契（至 {_fmt_time(item['expires_at'])}）")
            rows.append([
                InlineKeyboardButton(
                    text=f"同意 {item['partner_name']}",
                    callback_data=await action_callback_data(
                        user_id, f"bond:pconfirm:{item['bond_id']}")),
                InlineKeyboardButton(
                    text=f"婉拒 {item['partner_name']}",
                    callback_data=await action_callback_data(
                        user_id, f"bond:pdecline:{item['bond_id']}")),
            ])
    if state["pending_outgoing"]:
        lines.append("已递出的结契帖：")
        for item in state["pending_outgoing"]:
            lines.append(f"- {item['partner_name']} 待确认（至 {_fmt_time(item['expires_at'])}）")
    if state["cooldown_until"]:
        lines.append(f"解契冷却至：{_fmt_time(state['cooldown_until'])}")
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _append_communion_rows(lines: list[str], rows: list[list[InlineKeyboardButton]],
                                 user_id: int, partner: dict, session: dict | None) -> None:
    if not session:
        lines.append("共修：本周可邀道侣同步共修一次。")
        rows.append([
            InlineKeyboardButton(
                text="发起共修",
                callback_data=await action_callback_data(
                    user_id, f"bond:cminvite:{BONDS.KIND_PARTNER}:{partner['partner_id']}")),
        ])
        return
    if session["status"] == communion.STATUS_PENDING:
        if session["initiator_id"] == user_id:
            lines.append(f"共修：邀帖已递出，至 {_fmt_time(session['expires_at'])} 前有效。")
            return
        lines.append(f"共修：道侣邀你同参，至 {_fmt_time(session['expires_at'])} 前有效。")
        rows.append([
            InlineKeyboardButton(
                text="确认共修",
                callback_data=await action_callback_data(
                    user_id, f"bond:cmconfirm:{session['session_id']}")),
        ])
        return
    if session["status"] == communion.STATUS_ACTIVE:
        lines.append(f"共修：进行中，至 {_fmt_time(session['end_at'])} 可收束。")
        rows.append([
            InlineKeyboardButton(
                text="收束共修",
                callback_data=await action_callback_data(
                    user_id, f"bond:cmcomplete:{session['session_id']}")),
        ])


async def render_request_confirm(user_id: int, op: str, other_id: int):
    mentor_id, disciple_id = (other_id, user_id) if op == "拜师" else (user_id, other_id)
    res = await bonds_service.preview_mentor_request(mentor_id, disciple_id, user_id)
    if res["status"] != "ok":
        return _result_text(res), section_back_markup("↩️ 返回师徒", "nav:master")
    text = (
        f"🤝 {op}确认\n"
        f"师父：{res['mentor_name']}\n"
        f"徒弟：{res['disciple_name']}\n"
        "解除后重拜，出师累计活跃天数从 0 重计。请确认双方知晓此规。"
    )
    rows = [[InlineKeyboardButton(
        text="递出拜师帖",
        callback_data=await action_callback_data(
            user_id, f"bond:create:{mentor_id}:{disciple_id}"))]]
    rows.append([InlineKeyboardButton(text="↩️ 返回师徒", callback_data="nav:master")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def render_partner_request_confirm(user_id: int, other_id: int):
    res = await bonds_service.preview_partner_request(user_id, other_id, user_id)
    if res["status"] != "ok":
        return _result_text(res), section_back_markup("↩️ 返回道侣", "nav:partner")
    text = (
        "💞 结契确认\n"
        f"发起：{res['a_name']}\n"
        f"对方：{res['b_name']}\n"
        f"需双方金丹期以上；确认时消耗 1 枚绑定{BONDS.PARTNER_TOKEN_ITEM}。"
    )
    rows = [[InlineKeyboardButton(
        text="递出结契帖",
        callback_data=await action_callback_data(
            user_id, f"bond:pcreate:{user_id}:{other_id}"))]]
    rows.append([InlineKeyboardButton(text="↩️ 返回道侣", callback_data="nav:partner")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    action = res.get("action")
    if s == "ok" and action == "pcreate":
        return "结契帖已递出，待对方确认。"
    if s == "ok" and action == "pconfirm":
        return "同心结已应誓，道侣名分自此立下。"
    if s == "ok" and action == "pdecline":
        return "已婉拒这份结契帖。"
    if s == "ok" and action == "pdissolve":
        return f"道侣缘契已解。七日冷却至 {_fmt_time(res['cooldown_until'])}。"
    if s == "ok" and action == "pgift":
        return f"已赠出 {item_name(res['item'])}×{res['qty']}，赠礼仍为绑定。"
    if s == "ok" and action == "cminvite":
        return f"共修帖已递出，需在 {_fmt_time(res['expires_at'])} 前确认。"
    if s == "ok" and action == "cmconfirm":
        return f"共修已启，静待至 {_fmt_time(res['end_at'])} 后收束。"
    if s == "ok" and action == "cmcomplete":
        if not res.get("settled", True):
            return "此场共修此前已收束，奖励不会重复发放。"
        return "共修圆满，修为包已各归其主。"
    if s == "ok" and res.get("cultivation"):
        return f"传功已成，徒弟修为 +{res['cultivation']}。"
    if s == "ok" and res.get("titles") is not None:
        title = "，新得尊号：" + "、".join(t["title"] for t in res["titles"]) if res["titles"] else ""
        return f"弟子功成出师，师徒双方皆得传承礼{title}。"
    if s == "ok" and res.get("cooldown_until"):
        return f"师徒缘法已解。七日冷却至 {_fmt_time(res['cooldown_until'])}；重拜后出师活跃天数从 0 重计。"
    if s == "ok" and action == "create":
        return "拜师帖已递出，待对方确认。"
    if s == "ok" and action == "confirm":
        return "师徒名分已定，传承香火自此相续。"
    if s == "ok" and action == "decline":
        return "已婉拒这份拜师帖。"
    if s == "not_found":
        return "未寻得这份缘法。"
    if s == "bad_request":
        if action and action.startswith("p"):
            return "不可与自己结为道侣。"
        return "不可与自己结为师徒。"
    if s == "bad_target":
        return "不可邀自己共修。"
    if s == "bad_kind":
        return "此缘法类型不合。"
    if s == "forbidden":
        return "此事与你无关，不可代人做主。"
    if s == "missing":
        return NEED_START
    if s == "mentor_realm_low":
        return "师父至少需元婴期，方可开坛授业。"
    if s == "disciple_realm_high":
        return "徒弟需筑基圆满及以下，方可入门承教。"
    if s == "cooldown":
        return f"缘法尚在冷却，需等到 {_fmt_time(res.get('cooldown_until') or res.get('until'))}。"
    if s == "already_has_mentor":
        return "徒弟已有师父或待确认拜师帖。"
    if s == "already_has_partner":
        return "已有道侣或待确认结契帖。"
    if s == "too_many":
        return f"师父门下 active 徒弟已满（上限 {res['limit']}）。"
    if s == "not_pending":
        return "这份缘帖已不在待确认状态。"
    if s == "expired":
        return "这份缘帖已过期。"
    if s == "need_counterparty":
        return "需由另一方确认，不可自证。"
    if s == "not_active":
        if action and (action.startswith("p") or action.startswith("cm")):
            return "当前没有 active 道侣关系。"
        return "当前没有 active 师徒关系。"
    if s == "realm_low":
        return "双方至少需金丹期，方可缔结道侣。"
    if s == "no_token":
        return f"确认结契需消耗 1 枚绑定{item_name(res['item'])}。"
    if s == "no_stone":
        return f"解除道侣需 {res['need']} 灵石，当前仅有 {res['have']}。"
    if s == "mirror_missing":
        return "这段道侣镜像缘契缺失，请稍后再试。"
    if s == "bad_item":
        return f"{item_name(res['item'])}不在道侣互赠白名单。"
    if s == "no_item":
        return f"储物袋中缺少绑定{item_name(res['item'])}（需 {res['need']}）。"
    if s == "inactive_today":
        return "徒弟今日尚无前台修行，暂不可传功。"
    if s == "daily_done":
        if action == "pgift":
            return "今日已向道侣赠过礼。"
        return "今日已向这名徒弟传功。"
    if s == "has_open_session":
        return "已有一场共修邀约或仪式未了结。"
    if s == "weekly_used":
        return "本周共修名额已用，下周再同参。"
    if s == "busy":
        return "有道友正忙于他事，暂不可开启共修。"
    if s == "wounded":
        return "有道友伤势未复，暂不可开启共修。"
    if s == "not_started":
        return "共修尚未开始。"
    if s == "not_ready":
        return f"共修火候未足，需等到 {_fmt_time(res['end_at'])}。"
    if s == "interrupted":
        return "仪式中途被前台行动打断，本周次数已用，不发奖励。"
    if s == "disciple_realm_low":
        return "徒弟尚未至元婴初期，不能出师。"
    if s == "active_days_low":
        return f"活跃天数不足（需 {res['need']}，现有 {res['have']}）。"
    if s == "already_graduated":
        return "这段师徒缘已功成出师。"
    if s == "disciple_realm_high":
        return "徒弟境界已不合拜师门槛。"
    return "缘法事务未成。"


@router.message(Command("master"))
async def cmd_master(message: Message):
    parts = message.text.split()
    if len(parts) == 3 and parts[1] in {"拜师", "收徒"} and parts[2].isdigit():
        text, markup = await render_request_confirm(message.from_user.id, parts[1], int(parts[2]))
        await message.answer(text, reply_markup=markup)
        return
    text, markup = await render_master(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.message(Command("partner"))
async def cmd_partner(message: Message):
    if await guard_private_message(message):
        return
    parts = message.text.split()
    if len(parts) == 3 and parts[1] == "结契" and parts[2].isdigit():
        text, markup = await render_partner_request_confirm(message.from_user.id, int(parts[2]))
        await message.answer(text, reply_markup=markup)
        return
    text, markup = await render_partner(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:master")
async def cb_master(callback: CallbackQuery):
    text, markup = await render_master(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data == "nav:partner")
async def cb_partner(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_partner(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


def _action_back_markup(op: str) -> InlineKeyboardMarkup:
    if op in {"pcreate", "pconfirm", "pdecline", "pdissolve",
              "pgift", "cminvite", "cmconfirm", "cmcomplete"}:
        return section_back_markup("↩️ 返回道侣", "nav:partner")
    return section_back_markup("↩️ 返回师徒", "nav:master")


@router.callback_query(F.data.startswith("bond:"))
async def cb_bond_action(callback: CallbackQuery):
    if (callback.message and not is_private_chat(callback.message.chat)
            and not _is_master_callback(callback.data)):
        if await guard_private_callback(callback):
            return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("bond:"):
        return
    uid = callback.from_user.id
    parts = action.split(":")
    op = parts[1] if len(parts) > 1 else ""
    try:
        if op == "create" and len(parts) == 4:
            res = await bonds_service.create_pending_mentor_request(
                int(parts[2]), int(parts[3]), initiator_id=uid)
        elif op == "confirm" and len(parts) == 3:
            res = await bonds_service.confirm_pending_mentor_request(int(parts[2]), uid)
        elif op == "decline" and len(parts) == 3:
            res = await bonds_service.decline_pending_mentor_request(int(parts[2]), uid)
        elif op == "dissolve" and len(parts) == 3:
            res = await bonds_service.dissolve_active_bond(int(parts[2]), uid)
        elif op == "transfer" and len(parts) == 3:
            res = await bonds_service.grant_daily_mentor_transfer(uid, int(parts[2]))
        elif op == "graduate" and len(parts) == 3:
            res = await bonds_service.graduate_mentor_bond(int(parts[2]), uid)
        elif op == "pcreate" and len(parts) == 4:
            res = await bonds_service.create_pending_partner_request(
                int(parts[2]), int(parts[3]), initiator_id=uid)
        elif op == "pconfirm" and len(parts) == 3:
            res = await bonds_service.confirm_pending_partner_request(int(parts[2]), uid)
        elif op == "pdecline" and len(parts) == 3:
            res = await bonds_service.decline_pending_partner_request(int(parts[2]), uid)
        elif op == "pdissolve" and len(parts) == 3:
            res = await bonds_service.dissolve_active_bond(int(parts[2]), uid)
        elif op == "pgift" and len(parts) == 3:
            res = await bonds_service.grant_daily_partner_gift(uid, parts[2])
        elif op == "cminvite" and len(parts) == 4:
            res = await communion.invite(parts[2], uid, int(parts[3]))
        elif op == "cmconfirm" and len(parts) == 3:
            res = await communion.confirm(int(parts[2]), uid)
        elif op == "cmcomplete" and len(parts) == 3:
            res = await communion.complete(int(parts[2]))
        else:
            res = {"status": "bad_request"}
    except ValueError:
        res = {"status": "bad_request"}
    if isinstance(res, dict):
        res = {**res, "action": op}
    await show(callback, _result_text(res), _action_back_markup(op))
    await callback.answer()
