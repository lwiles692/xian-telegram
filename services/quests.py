from __future__ import annotations

"""悬赏任务与成就。"""

import sqlite3
import time

from config import bonds as BONDS
from config.items import item_name
from config.quests import ACHIEVEMENTS, ONBOARDING_WINDOW_DAYS, QUESTS
from models import db
from services import bonds as bonds_service, character

DAY_SECONDS = 24 * 3600


def _day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _week(ts: int) -> str:
    return time.strftime("%Y-%W", time.localtime(ts))


def period_for(kind: str, now: int, created_at: int | None = None) -> str:
    if kind == "weekly":
        return _week(now)
    if kind == "onboarding":
        return f"onboarding:{int(created_at or 0)}"
    return _day(now)


def _onboarding_day(created_at: int | None, now: int) -> int | None:
    if created_at is None or now < int(created_at):
        return None
    day = (now - int(created_at)) // DAY_SECONDS + 1
    if 1 <= day <= ONBOARDING_WINDOW_DAYS:
        return int(day)
    return None


def _is_onboarding(quest: dict) -> bool:
    return quest.get("period") == "onboarding"


async def _character_created_at_conn(conn, user_id: int) -> int | None:
    cur = await conn.execute("SELECT created_at FROM characters WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return int(row["created_at"]) if row else None


async def _quest_open_conn(conn, user_id: int, quest: dict,
                           now: int, created_at: int | None = None) -> dict:
    if not _is_onboarding(quest):
        return {"open": True, "period": period_for(quest["period"], now)}
    if created_at is None:
        created_at = await _character_created_at_conn(conn, user_id)
    day = _onboarding_day(created_at, now)
    if day is None:
        return {"open": False, "status": "not_open"}
    unlock_day = int(quest.get("unlock_day", 1))
    if day < unlock_day:
        return {"open": False, "status": "not_open", "day": day, "unlock_day": unlock_day}
    return {"open": True, "period": period_for("onboarding", now, created_at),
            "day": day, "unlock_day": unlock_day}


async def record_event_conn(conn, user_id: int, event_type: str,
                            payload: dict | None = None, now: int = None):
    now = int(time.time()) if now is None else now
    payload = payload or {}
    changed = []
    created_at = None
    if any(quest["event"] == event_type and _is_onboarding(quest)
           for quest in QUESTS.values()):
        created_at = await _character_created_at_conn(conn, user_id)
    for key, quest in QUESTS.items():
        if quest["event"] != event_type:
            continue
        gate = await _quest_open_conn(conn, user_id, quest, now, created_at)
        if not gate["open"]:
            continue
        period = gate["period"]
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
        await _grant_reward_conn(conn, user_id, achievement.get("reward", {}), now)
        unlocked.append(key)
    return {"quests": changed, "achievements": unlocked}


async def _grant_reward_conn(conn, user_id: int, reward: dict, now: int = None):
    now = int(time.time()) if now is None else int(now)
    stone = int(reward.get("stone", 0) or 0)
    if stone:
        await conn.execute(
            "UPDATE characters SET spirit_stone = spirit_stone + ? WHERE user_id=?",
            (stone, user_id))
    stamina = int(reward.get("stamina", 0) or 0)
    if stamina:
        await character.grant_stamina_conn(conn, user_id, stamina, now)
    for key, qty in (reward.get("items") or {}).items():
        if qty <= 0:
            continue
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = qty + ?",
            (user_id, key, qty, qty))
    for key, qty in (reward.get("bound_items") or {}).items():
        if qty <= 0:
            continue
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,1,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = qty + ?",
            (user_id, key, qty, qty))


async def _grant_onboarding_bond_reward_conn(conn, user_id: int, quest_key: str,
                                             now: int) -> dict:
    cur = await conn.execute(
        "SELECT id, a_id, b_id FROM social_bonds "
        "WHERE kind=? AND b_id=? AND status=? LIMIT 1",
        (BONDS.KIND_MENTOR, user_id, BONDS.STATUS_ACTIVE))
    bond = await cur.fetchone()
    await cur.close()
    if not bond:
        return {"status": "no_active_bond"}
    milestone = f"onboarding:{quest_key}"
    try:
        cur = await conn.execute(
            "INSERT INTO bond_milestones(bond_kind, a_id, b_id, milestone, claimed_at) "
            "VALUES(?,?,?,?,?)",
            (BONDS.KIND_MENTOR, bond["a_id"], bond["b_id"], milestone, now))
    except sqlite3.IntegrityError:
        return {"status": "already_claimed", "mentor_id": bond["a_id"],
                "disciple_id": bond["b_id"]}
    await cur.close()
    await _grant_reward_conn(conn, bond["b_id"], BONDS.ONBOARDING_DISCIPLE_LINK_REWARD, now)
    await _grant_reward_conn(conn, bond["a_id"], BONDS.ONBOARDING_MENTOR_LINK_REWARD, now)
    return {"status": "ok", "mentor_id": bond["a_id"], "disciple_id": bond["b_id"],
            "milestone": milestone,
            "mentor_reward": BONDS.ONBOARDING_MENTOR_LINK_REWARD,
            "disciple_reward": BONDS.ONBOARDING_DISCIPLE_LINK_REWARD}


async def list_status(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    created_at = await db.fetchone(
        "SELECT created_at FROM characters WHERE user_id=?", (user_id,))
    created = int(created_at["created_at"]) if created_at else None
    rows = await db.fetchall(
        "SELECT quest_key, period, progress, claimed FROM quest_progress WHERE user_id=?",
        (user_id,))
    by_key_period = {(row["quest_key"], row["period"]): row for row in rows}
    quests = []
    for key, quest in QUESTS.items():
        if _is_onboarding(quest):
            day = _onboarding_day(created, now)
            if day is None or day < int(quest.get("unlock_day", 1)):
                continue
            period = period_for("onboarding", now, created)
        else:
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
    async with db.transaction() as conn:
        gate = await _quest_open_conn(conn, user_id, quest, now)
        if not gate["open"]:
            return {"status": gate.get("status", "not_open")}
        period = gate["period"]
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
        await _grant_reward_conn(conn, user_id, quest.get("reward", {}), now)
        bond_activity = await bonds_service.record_disciple_activity(conn, user_id, now)
        bond_reward = None
        if _is_onboarding(quest):
            bond_reward = await _grant_onboarding_bond_reward_conn(conn, user_id, quest_key, now)
    return {"status": "ok", "quest": quest["name"], "reward": quest.get("reward", {}),
            "bond_activity": bond_activity, "bond_reward": bond_reward}


def reward_text(reward: dict) -> str:
    parts = []
    if reward.get("stone"):
        parts.append(f"灵石 +{reward['stone']}")
    if reward.get("stamina"):
        parts.append(f"精力 +{reward['stamina']}")
    for key, qty in (reward.get("items") or {}).items():
        parts.append(f"{item_name(key)}×{qty}")
    for key, qty in (reward.get("bound_items") or {}).items():
        parts.append(f"绑定{item_name(key)}×{qty}")
    return "、".join(parts) if parts else "无"


def achievement_name(key: str) -> str:
    return ACHIEVEMENTS.get(key, {}).get("name", key)
