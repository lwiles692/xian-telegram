"""悬赏任务与成就。"""
from __future__ import annotations

import time

from config.items import item_name
from config.quests import ACHIEVEMENTS, QUESTS
from models import db
from services import bonds as bonds_service, character


def _day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _week(ts: int) -> str:
    return time.strftime("%Y-%W", time.localtime(ts))


def period_for(kind: str, now: int) -> str:
    return _week(now) if kind == "weekly" else _day(now)


async def record_event_conn(conn, user_id: int, event_type: str,
                            payload: dict | None = None, now: int = None):
    now = int(time.time()) if now is None else now
    payload = payload or {}
    changed = []
    for key, quest in QUESTS.items():
        if quest["event"] != event_type:
            continue
        period = period_for(quest["period"], now)
        amount = int(payload.get("amount", 1) or 1)
        await conn.execute(
            "INSERT INTO quest_progress(user_id, quest_key, period, progress, claimed) "
            "VALUES(?,?,?,?,0) "
            "ON CONFLICT(user_id, quest_key, period) DO UPDATE SET "
            "progress = MIN(progress + ?, ?)",
            (user_id, key, period, min(amount, quest["target"]), amount, quest["target"]))
        changed.append(key)
    unlocked = []
    for key, achievement in ACHIEVEMENTS.items():
        if achievement["event"] != event_type:
            continue
        min_realm = achievement.get("min_target_realm")
        if min_realm is not None and int(payload.get("target_realm", -1)) < min_realm:
            continue
        cur = await conn.execute(
            "SELECT 1 FROM achievements WHERE user_id=? AND key=?",
            (user_id, key))
        exists = await cur.fetchone()
        await cur.close()
        if exists:
            continue
        await conn.execute(
            "INSERT INTO achievements(user_id, key, unlocked_at) VALUES(?,?,?)",
            (user_id, key, now))
        await _grant_reward_conn(conn, user_id, achievement.get("reward", {}))
        unlocked.append(key)
    return {"quests": changed, "achievements": unlocked}


async def _grant_reward_conn(conn, user_id: int, reward: dict):
    stone = int(reward.get("stone", 0) or 0)
    if stone:
        await conn.execute(
            "UPDATE characters SET spirit_stone = spirit_stone + ? WHERE user_id=?",
            (stone, user_id))
    for key, qty in (reward.get("items") or {}).items():
        if qty <= 0:
            continue
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = qty + ?",
            (user_id, key, qty, qty))


async def list_status(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    rows = await db.fetchall(
        "SELECT quest_key, period, progress, claimed FROM quest_progress WHERE user_id=?",
        (user_id,))
    by_key_period = {(row["quest_key"], row["period"]): row for row in rows}
    quests = []
    for key, quest in QUESTS.items():
        period = period_for(quest["period"], now)
        row = by_key_period.get((key, period))
        progress = int(row["progress"]) if row else 0
        claimed = bool(row["claimed"]) if row else False
        quests.append({
            "key": key,
            "name": quest["name"],
            "period": quest["period"],
            "progress": progress,
            "target": quest["target"],
            "claimed": claimed,
            "ready": progress >= quest["target"] and not claimed,
            "reward": quest.get("reward", {}),
        })
    unlocked = await db.fetchall(
        "SELECT key, unlocked_at FROM achievements WHERE user_id=? ORDER BY unlocked_at DESC",
        (user_id,))
    return {"quests": quests, "achievements": [dict(row) for row in unlocked]}


async def claim(user_id: int, quest_key: str, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    quest = QUESTS.get(quest_key)
    if not quest:
        return {"status": "bad_quest"}
    period = period_for(quest["period"], now)
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT progress, claimed FROM quest_progress "
            "WHERE user_id=? AND quest_key=? AND period=?",
            (user_id, quest_key, period))
        row = await cur.fetchone()
        await cur.close()
        if not row or row["progress"] < quest["target"]:
            return {"status": "not_ready"}
        if row["claimed"]:
            return {"status": "claimed"}
        await conn.execute(
            "UPDATE quest_progress SET claimed=1 WHERE user_id=? AND quest_key=? AND period=?",
            (user_id, quest_key, period))
        await _grant_reward_conn(conn, user_id, quest.get("reward", {}))
        bond_activity = await bonds_service.record_disciple_activity(conn, user_id, now)
    return {"status": "ok", "quest": quest["name"], "reward": quest.get("reward", {}),
            "bond_activity": bond_activity}


def reward_text(reward: dict) -> str:
    parts = []
    if reward.get("stone"):
        parts.append(f"灵石 +{reward['stone']}")
    for key, qty in (reward.get("items") or {}).items():
        parts.append(f"{item_name(key)}×{qty}")
    return "、".join(parts) if parts else "无"


def achievement_name(key: str) -> str:
    return ACHIEVEMENTS.get(key, {}).get("name", key)
