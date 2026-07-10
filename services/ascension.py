"""飞升点：化神圆满后的账号级小幅成长。"""
from __future__ import annotations

import json
import time

from config import ascension as CFG
from config import realms as R
from models import db
from services import game_events


def _week(now: int) -> str:
    return time.strftime("%Y-%W", time.localtime(now))


def _trial_unlocked(realm: int, stage: int) -> bool:
    if realm > CFG.TRIAL_UNLOCK_REALM:
        return True
    return realm == CFG.TRIAL_UNLOCK_REALM and stage == R.num_stages(realm) - 1


async def get(user_id: int) -> dict:
    row = await db.fetchone("SELECT * FROM ascension WHERE user_id=?", (user_id,))
    if not row:
        return {"user_id": user_id, "level": 0, "points": 0, "spent": {}}
    return {
        "user_id": row["user_id"],
        "level": row["level"],
        "points": row["points"],
        "spent": json.loads(row["spent_json"] or "{}"),
        "updated_at": row["updated_at"],
    }


async def add_points_conn(conn, user_id: int, points: int, now: int = None):
    now = int(time.time()) if now is None else now
    if points <= 0:
        return
    await conn.execute(
        "INSERT INTO ascension(user_id, level, points, spent_json, updated_at) "
        "VALUES(?,0,?,'{}',?) "
        "ON CONFLICT(user_id) DO UPDATE SET points=points+?, updated_at=?",
        (user_id, points, now, points, now))


async def trial(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT realm, stage, daohang FROM characters WHERE user_id=?", (user_id,))
        ch = await cur.fetchone()
        await cur.close()
        if not ch:
            return {"status": "missing"}
        if not _trial_unlocked(ch["realm"], ch["stage"]):
            return {"status": "locked"}
        # spec §6.2：每周仅可完成一次飞升试炼，防止囤道行无限刷飞升点旁路 5 级硬上限。
        week = _week(now)
        cur = await conn.execute("SELECT last_trial_week FROM ascension WHERE user_id=?", (user_id,))
        asc = await cur.fetchone()
        await cur.close()
        if asc and asc["last_trial_week"] == week:
            return {"status": "weekly_done", "week": week}
        if ch["daohang"] < CFG.TRIAL_DAOHANG_COST:
            return {"status": "no_daohang", "need": CFG.TRIAL_DAOHANG_COST, "have": ch["daohang"]}
        await conn.execute(
            "UPDATE characters SET daohang=daohang-? WHERE user_id=?",
            (CFG.TRIAL_DAOHANG_COST, user_id))
        await add_points_conn(conn, user_id, CFG.TRIAL_POINT_REWARD, now)
        await conn.execute(
            "UPDATE ascension SET last_trial_week=? WHERE user_id=?", (week, user_id))
        await game_events.emit_conn(
            conn, user_id, "ascension.trial",
            {"points": CFG.TRIAL_POINT_REWARD, "amount": CFG.TRIAL_POINT_REWARD}, now)
        return {"status": "ok", "points": CFG.TRIAL_POINT_REWARD, "cost": CFG.TRIAL_DAOHANG_COST}


async def upgrade_passive(user_id: int, passive_key: str, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    if passive_key not in CFG.PASSIVES:
        return {"status": "bad_passive"}
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM ascension WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return {"status": "no_points", "need": CFG.POINTS_PER_PASSIVE_LEVEL, "have": 0}
        spent = json.loads(row["spent_json"] or "{}")
        current = int(spent.get(passive_key, 0))
        if current >= CFG.PASSIVE_CAP:
            return {"status": "max", "level": current, "cap": CFG.PASSIVE_CAP}
        if row["points"] < CFG.POINTS_PER_PASSIVE_LEVEL:
            return {"status": "no_points", "need": CFG.POINTS_PER_PASSIVE_LEVEL, "have": row["points"]}
        spent[passive_key] = current + 1
        await conn.execute(
            "UPDATE ascension SET points=points-?, level=level+1, spent_json=?, updated_at=? "
            "WHERE user_id=?",
            (CFG.POINTS_PER_PASSIVE_LEVEL, json.dumps(spent, ensure_ascii=False), now, user_id))
        passive_level = current + 1
        total_level = int(row["level"]) + 1
        title = CFG.ascension_title(total_level)
        # spec §6.3 T3.5：被动升级触发群播报；总阶晋档时附带尊号解锁。
        await game_events.emit_conn(
            conn, user_id, "ascension.upgrade",
            {"passive": passive_key, "passive_name": CFG.passive_name(passive_key),
             "level": passive_level, "total_level": total_level, "title": title}, now)
        return {"status": "ok", "passive": passive_key, "level": passive_level,
                "total_level": total_level, "name": CFG.passive_name(passive_key),
                "title": title}


async def passive_bonuses(user_id: int) -> dict:
    state = await get(user_id)
    bonuses = {}
    for key, level in state.get("spent", {}).items():
        if key in CFG.PASSIVES:
            bonuses[key] = min(CFG.PASSIVE_CAP, int(level)) * 0.01
    return bonuses
