from __future__ import annotations

"""每日签到（spec §9/§12 指令表）。"""

import time

from config import realms as R
from models import db
from services import character as character_service, game_events

HUASHEN_AID_ITEM = "化神丹"
LIANXU_AID_ITEM = "炼虚丹"
YUANYING_REALM = 3
HUASHEN_REALM = 4
LIANXU_REALM = 5
DAILY_STAMINA_REWARD = 10


def _day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


async def _maybe_grant_aid_conn(conn, user_id: int, char, source_realm: int,
                                target_realm: int, item_key: str,
                                reason: str) -> dict | None:
    last_stage = R.num_stages(source_realm) - 1
    if char["realm"] != source_realm or char["stage"] != last_stage:
        return None
    if char["cultivation"] < R.advance_cost(source_realm, last_stage):
        return None
    cur = await conn.execute(
        "SELECT 1 FROM tribulation_sessions WHERE user_id=? AND target_realm=?",
        (user_id, target_realm))
    active_tribulation = await cur.fetchone()
    await cur.close()
    if active_tribulation:
        return None
    if await character_service.item_qty_conn(conn, user_id, item_key) > 0:
        return None
    await conn.execute(
        "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,1,1) "
        "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = qty + 1",
        (user_id, item_key))
    return {
        "item": item_key,
        "qty": 1,
        "bound": 1,
        "reason": reason,
    }


async def _maybe_grant_huashen_aid_conn(conn, user_id: int, char) -> dict | None:
    return await _maybe_grant_aid_conn(
        conn, user_id, char, YUANYING_REALM, HUASHEN_REALM,
        HUASHEN_AID_ITEM, "yuanying_full_aid")


async def _maybe_grant_lianxu_aid_conn(conn, user_id: int, char) -> dict | None:
    return await _maybe_grant_aid_conn(
        conn, user_id, char, HUASHEN_REALM, LIANXU_REALM,
        LIANXU_AID_ITEM, "huashen_full_aid")


async def checkin(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    day = _day(now)
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM characters WHERE user_id=?", (user_id,))
        char = await cur.fetchone()
        await cur.close()
        if not char:
            return {"status": "missing"}
        cur = await conn.execute("SELECT * FROM daily WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if row and row["last_checkin_day"] == day:
            return {"status": "done", "streak": row["streak"]}
        streak = (row["streak"] + 1) if row else 1
        reward = 80 + min(streak, 7) * 10
        await conn.execute(
            "INSERT INTO daily(user_id, last_checkin_day, streak) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET last_checkin_day=?, streak=?",
            (user_id, day, streak, day, streak))
        await conn.execute(
            "UPDATE characters SET spirit_stone = spirit_stone + ? WHERE user_id=?",
            (reward, user_id))
        stamina = await character_service.grant_stamina_conn(
            conn, user_id, DAILY_STAMINA_REWARD, now)
        aid = await _maybe_grant_huashen_aid_conn(conn, user_id, char)
        lianxu_aid = await _maybe_grant_lianxu_aid_conn(conn, user_id, char)
        await game_events.emit_conn(
            conn, user_id, "daily.checkin", {"streak": streak, "amount": 1}, now)
        return {
            "status": "ok",
            "streak": streak,
            "stone": reward,
            "stamina": stamina,
            "extra_items": [item for item in (aid, lianxu_aid) if item],
        }
