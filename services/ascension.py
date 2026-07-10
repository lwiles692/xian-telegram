"""飞升点：溢出凝点、飞升被动与叩问天门。"""
from __future__ import annotations

import json
import time

from config import ascension as CFG
from config import realms as R
from config.items import item_name
from models import db
from services import game_events


def _week(now: int) -> str:
    return time.strftime("%Y-%W", time.localtime(now))


def _trial_unlocked(realm: int, stage: int) -> bool:
    if realm > CFG.TRIAL_UNLOCK_REALM:
        return True
    return realm == CFG.TRIAL_UNLOCK_REALM and stage == R.num_stages(realm) - 1


async def _points_balance_conn(conn, user_id: int) -> int:
    cur = await conn.execute("SELECT points FROM ascension WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return int(row["points"] or 0) if row else 0


async def _record_points_event_conn(conn, user_id: int, source: str, delta: int,
                                    balance: int, now: int, meta: dict | None = None):
    await conn.execute(
        "INSERT INTO ascension_events(user_id, source, points_delta, balance_after, "
        "meta_json, created_at) VALUES(?,?,?,?,?,?)",
        (user_id, source, int(delta), int(balance),
         json.dumps(meta or {}, ensure_ascii=False), now))


def _format_state(row, now: int) -> dict:
    spent = json.loads(row["spent_json"] or "{}")
    current_week = _week(now)
    week_points = int(row["overflow_week_points"] or 0)
    if row["overflow_week"] != current_week:
        week_points = 0
    tianmen_level = int(row["tianmen_level"] or 0)
    return {
        "user_id": row["user_id"],
        "level": int(row["level"] or 0),
        "points": int(row["points"] or 0),
        "spent": spent,
        "updated_at": int(row["updated_at"] or 0),
        "overflow_remainder": int(row["overflow_remainder"] or 0),
        "overflow_week": current_week,
        "overflow_week_points": week_points,
        "tianmen_level": tianmen_level,
        "tianmen_progress": int(row["tianmen_progress"] or 0),
        "tianmen_next_cost": CFG.tianmen_next_cost(tianmen_level),
        "tianmen_title": CFG.tianmen_title(tianmen_level),
        "tianmen_unlocked": CFG.passives_maxed(spent),
    }


async def get(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    row = await db.fetchone("SELECT * FROM ascension WHERE user_id=?", (user_id,))
    if not row:
        return {
            "user_id": user_id,
            "level": 0,
            "points": 0,
            "spent": {},
            "overflow_remainder": 0,
            "overflow_week": _week(now),
            "overflow_week_points": 0,
            "tianmen_level": 0,
            "tianmen_progress": 0,
            "tianmen_next_cost": CFG.tianmen_next_cost(0),
            "tianmen_title": "",
            "tianmen_unlocked": False,
        }
    return _format_state(row, now)


async def add_points_conn(conn, user_id: int, points: int, now: int = None,
                          source: str = "system", meta: dict | None = None):
    now = int(time.time()) if now is None else now
    if points <= 0:
        return
    await conn.execute(
        "INSERT INTO ascension(user_id, level, points, spent_json, updated_at) "
        "VALUES(?,0,?,'{}',?) "
        "ON CONFLICT(user_id) DO UPDATE SET points=points+?, updated_at=?",
        (user_id, points, now, points, now))
    balance = await _points_balance_conn(conn, user_id)
    await _record_points_event_conn(
        conn, user_id, source, points, balance, now, meta)


async def spend_points_conn(conn, user_id: int, points: int, source: str,
                            now: int = None, meta: dict | None = None) -> bool:
    """原子扣除飞升点并写入流水，余额不足时不修改。"""
    now = int(time.time()) if now is None else now
    points = max(0, int(points or 0))
    if points <= 0:
        return True
    cur = await conn.execute(
        "UPDATE ascension SET points=points-?, updated_at=? "
        "WHERE user_id=? AND points>=?",
        (points, now, user_id, points))
    changed = cur.rowcount == 1
    await cur.close()
    if not changed:
        return False
    balance = await _points_balance_conn(conn, user_id)
    await _record_points_event_conn(
        conn, user_id, source, -points, balance, now, meta)
    return True


async def add_overflow_points_conn(conn, user_id: int, overflow_cultivation: int,
                                   now: int = None) -> dict:
    """将溢出修为按十万进一、每周十四点的规则凝成飞升点。"""
    now = int(time.time()) if now is None else now
    overflow_cultivation = max(0, int(overflow_cultivation or 0))
    week = _week(now)
    cur = await conn.execute("SELECT * FROM ascension WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    if not row:
        await conn.execute(
            "INSERT INTO ascension(user_id, level, points, spent_json, updated_at, "
            "overflow_week) VALUES(?,0,0,'{}',?,?)",
            (user_id, now, week))
        remainder = 0
        week_points = 0
    else:
        remainder = int(row["overflow_remainder"] or 0)
        week_points = int(row["overflow_week_points"] or 0)
        if row["overflow_week"] != week:
            week_points = 0

    available = max(0, CFG.OVERFLOW_WEEKLY_CAP - week_points)
    if overflow_cultivation <= 0 or available <= 0:
        return {
            "points": 0,
            "remainder": remainder,
            "week": week,
            "week_points": week_points,
            "week_cap": CFG.OVERFLOW_WEEKLY_CAP,
        }

    total = remainder + overflow_cultivation
    possible = total // CFG.OVERFLOW_CULTIVATION_PER_POINT
    granted = min(possible, available)
    if possible > available:
        # 超出周额度的完整十万修为直接沉淀，只保留不足十万的零头。
        new_remainder = total % CFG.OVERFLOW_CULTIVATION_PER_POINT
    else:
        new_remainder = total - granted * CFG.OVERFLOW_CULTIVATION_PER_POINT
    new_week_points = week_points + granted
    await conn.execute(
        "UPDATE ascension SET points=points+?, overflow_remainder=?, overflow_week=?, "
        "overflow_week_points=?, updated_at=? WHERE user_id=?",
        (granted, new_remainder, week, new_week_points, now, user_id))
    if granted:
        balance = await _points_balance_conn(conn, user_id)
        await _record_points_event_conn(
            conn, user_id, "overflow", granted, balance, now,
            {"overflow_cultivation": overflow_cultivation,
             "remainder": new_remainder, "week": week,
             "week_points": new_week_points})
    return {
        "points": granted,
        "remainder": new_remainder,
        "week": week,
        "week_points": new_week_points,
        "week_cap": CFG.OVERFLOW_WEEKLY_CAP,
    }


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
        # spec §6.2：每周仅可完成一次飞升试炼，防止囤道行无限刷飞升点。
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
        await add_points_conn(
            conn, user_id, CFG.TRIAL_POINT_REWARD, now, source="trial")
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
        balance = int(row["points"]) - CFG.POINTS_PER_PASSIVE_LEVEL
        await conn.execute(
            "UPDATE ascension SET points=?, level=level+1, spent_json=?, updated_at=? "
            "WHERE user_id=?",
            (balance, json.dumps(spent, ensure_ascii=False), now, user_id))
        await _record_points_event_conn(
            conn, user_id, "passive_upgrade", -CFG.POINTS_PER_PASSIVE_LEVEL,
            balance, now, {"passive": passive_key, "level": current + 1})
        passive_level = current + 1
        total_level = int(row["level"]) + 1
        title = CFG.ascension_title(total_level)
        await game_events.emit_conn(
            conn, user_id, "ascension.upgrade",
            {"passive": passive_key, "passive_name": CFG.passive_name(passive_key),
             "level": passive_level, "total_level": total_level, "title": title}, now)
        return {"status": "ok", "passive": passive_key, "level": passive_level,
                "total_level": total_level, "name": CFG.passive_name(passive_key),
                "title": title}


async def contribute_tianmen(user_id: int, amount: int | None,
                             now: int = None) -> dict:
    """投入飞升点叩问天门；amount=None 表示投入全部余额。"""
    now = int(time.time()) if now is None else now
    if amount is not None and int(amount) not in CFG.TIANMEN_CONTRIBUTIONS:
        return {"status": "bad_amount"}
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM ascension WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return {"status": "no_points", "need": int(amount or 1), "have": 0}
        spent_passives = json.loads(row["spent_json"] or "{}")
        if not CFG.passives_maxed(spent_passives):
            return {"status": "passives_not_max"}
        balance = int(row["points"] or 0)
        contribution = balance if amount is None else int(amount)
        if contribution <= 0 or balance < contribution:
            return {"status": "no_points", "need": max(1, contribution), "have": balance}

        level = int(row["tianmen_level"] or 0)
        progress = int(row["tianmen_progress"] or 0)
        remaining = contribution
        crossed = []
        while remaining > 0:
            need = CFG.tianmen_next_cost(level) - progress
            if remaining < need:
                progress += remaining
                remaining = 0
                break
            remaining -= need
            level += 1
            progress = 0
            crossed.append(level)

        new_balance = balance - contribution
        await conn.execute(
            "UPDATE ascension SET points=?, tianmen_level=?, tianmen_progress=?, "
            "updated_at=? WHERE user_id=?",
            (new_balance, level, progress, now, user_id))
        await _record_points_event_conn(
            conn, user_id, "tianmen", -contribution, new_balance, now,
            {"level": level, "progress": progress, "crossed": crossed})

        rewards = []
        milestones = []
        for crossed_level in crossed:
            reward = CFG.TIANMEN_MILESTONES.get(crossed_level)
            if not reward:
                continue
            milestones.append(crossed_level)
            await conn.execute(
                "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,1,?) "
                "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty=qty+?",
                (user_id, reward["item"], reward["qty"], reward["qty"]))
            rewards.append({"item": reward["item"], "name": item_name(reward["item"]),
                            "qty": reward["qty"], "level": crossed_level})
        if milestones:
            await game_events.emit_conn(
                conn, user_id, "ascension.tianmen",
                {"level": milestones[-1], "title": CFG.tianmen_title(milestones[-1]),
                 "milestones": milestones}, now)
        return {
            "status": "tianmen_ok",
            "spent": contribution,
            "points": new_balance,
            "level": level,
            "progress": progress,
            "next_cost": CFG.tianmen_next_cost(level),
            "title": CFG.tianmen_title(level),
            "crossed": crossed,
            "rewards": rewards,
        }


async def passive_bonuses(user_id: int) -> dict:
    state = await get(user_id)
    bonuses = {}
    for key, level in state.get("spent", {}).items():
        if key in CFG.PASSIVES:
            bonuses[key] = min(CFG.PASSIVE_CAP, int(level)) * 0.01
    return bonuses
