"""/daily —— 每日签到。"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from handlers.common import NEED_START
from services import daily

router = Router()


def _ok_text(res: dict) -> str:
    lines = [
        f"📅 签到成功，连续 {res['streak']} 日，"
        f"灵石 +{res['stone']}，精力 +{res['stamina']}。"
    ]
    for extra in res.get("extra_items", []):
        if extra.get("item") == daily.HUASHEN_AID_ITEM:
            lines.append("凝婴问道补给：化神丹 ×1（绑定）。")
    return "\n".join(lines)


@router.message(Command("daily"))
async def cmd_daily(message: Message):
    res = await daily.checkin(message.from_user.id)
    if res["status"] == "ok":
        await message.answer(_ok_text(res))
    elif res["status"] == "missing":
        await message.answer(NEED_START)
    else:
        await message.answer(f"今日已签到，连续 {res['streak']} 日。")
