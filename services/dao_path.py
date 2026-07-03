"""道途：元婴起的专修长线。"""
from __future__ import annotations

import time

from config import dao_paths as CFG
from models import db
from services import game_events


async def list_paths(user_id: int) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM dao_paths WHERE user_id=? ORDER BY active DESC, unlocked_at, path_key",
        (user_id,))
    return [_format_row(row) for row in rows]


async def active_path(user_id: int):
    row = await db.fetchone(
        "SELECT * FROM dao_paths WHERE user_id=? AND active=1 LIMIT 1",
        (user_id,))
    return _format_row(row) if row else None


async def active_bonuses(user_id: int) -> dict:
    row = await db.fetchone(
        "SELECT path_key, rank, xp FROM dao_paths WHERE user_id=? AND active=1 LIMIT 1",
        (user_id,))
    if not row:
        return {}
    return CFG.bonuses_for(row["path_key"], row["rank"], row["xp"])


async def unlock(user_id: int, path_key: str, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    if path_key not in CFG.DAO_PATHS:
        return {"status": "bad_path"}
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT realm, stage FROM characters WHERE user_id=?", (user_id,))
        char = await cur.fetchone()
        await cur.close()
        if not char:
            return {"status": "missing"}
        if char["realm"] < CFG.UNLOCK_REALM:
            return {"status": "locked", "need_realm": CFG.UNLOCK_REALM}
        cur = await conn.execute(
            "SELECT 1 FROM dao_paths WHERE user_id=? AND path_key=?",
            (user_id, path_key))
        exists = await cur.fetchone()
        await cur.close()
        if exists:
            await _set_active(conn, user_id, path_key)
            return {"status": "active", "path": CFG.path_name(path_key)}
        cur = await conn.execute("SELECT COUNT(*) AS n FROM dao_paths WHERE user_id=?", (user_id,))
        count = (await cur.fetchone())["n"]
        await cur.close()
        if count > 0:
            return {"status": "need_switch", "path": CFG.path_name(path_key)}
        await conn.execute(
            "INSERT INTO dao_paths(user_id, path_key, xp, rank, active, unlocked_at) "
            "VALUES(?,?,0,0,1,?)",
            (user_id, path_key, now))
        await conn.execute(
            "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
            "VALUES(?,?,?,0,?)",
            (user_id, path_key, "unlock", now))
        return {"status": "unlocked", "path": CFG.path_name(path_key), "rank": 0,
                "rank_name": CFG.rank_name(0)}


async def rank_up(user_id: int, path_key: str = None, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        row = await _path_row(conn, user_id, path_key)
        if not row:
            return {"status": "not_unlocked"}
        target_rank = row["rank"] + 1
        if target_rank >= len(CFG.RANK_NAMES):
            return {"status": "max", "rank": row["rank"]}
        cost = CFG.RANK_UP_COSTS[target_rank]
        cur = await conn.execute("SELECT daohang FROM characters WHERE user_id=?", (user_id,))
        ch = await cur.fetchone()
        await cur.close()
        if not ch:
            return {"status": "missing"}
        if ch["daohang"] < cost["daohang"]:
            return {"status": "no_daohang", "need": cost["daohang"], "have": ch["daohang"]}
        for key, qty in cost.get("items", {}).items():
            have = await _item_qty_conn(conn, user_id, key)
            if have < qty:
                return {"status": "no_material", "item": key, "need": qty, "have": have}
        ascension_points = int(cost.get("ascension_points", 0) or 0)
        if ascension_points:
            cur = await conn.execute("SELECT points FROM ascension WHERE user_id=?", (user_id,))
            asc = await cur.fetchone()
            await cur.close()
            have_points = int(asc["points"] or 0) if asc else 0
            if have_points < ascension_points:
                return {"status": "no_ascension_points", "need": ascension_points,
                        "have": have_points}
        await conn.execute(
            "UPDATE characters SET daohang=daohang-? WHERE user_id=?",
            (cost["daohang"], user_id))
        for key, qty in cost.get("items", {}).items():
            await _consume_item_conn(conn, user_id, key, qty)
        if ascension_points:
            await conn.execute(
                "UPDATE ascension SET points=points-?, updated_at=? WHERE user_id=?",
                (ascension_points, now, user_id))
        await conn.execute(
            "UPDATE dao_paths SET rank=? WHERE user_id=? AND path_key=?",
            (target_rank, user_id, row["path_key"]))
        await conn.execute(
            "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
            "VALUES(?,?,?,?,?)",
            (user_id, row["path_key"], "rank_up", target_rank, now))
        await game_events.emit_conn(
            conn, user_id, "dao_path.rank_up",
            {"path_key": row["path_key"], "rank": target_rank,
             "path": CFG.path_name(row["path_key"]), "rank_name": CFG.rank_name(target_rank)}, now)
        return {"status": "ok", "path": CFG.path_name(row["path_key"]), "rank": target_rank,
                "rank_name": CFG.rank_name(target_rank), "cost": cost}


async def refine(user_id: int, path_key: str = None, now: int = None) -> dict:
    """道途淬炼：花道行深化本道（升 xp 层，走既有 BUFF clamp），高境界道行的出口。"""
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        row = await _path_row(conn, user_id, path_key)
        if not row:
            return {"status": "not_unlocked"}
        level = int(row["xp"] or 0)
        if level >= CFG.REFINE_MAX_LEVEL:
            return {"status": "refine_max", "level": level}
        cost = CFG.refine_cost(level)
        cur = await conn.execute("SELECT daohang FROM characters WHERE user_id=?", (user_id,))
        ch = await cur.fetchone()
        await cur.close()
        if not ch:
            return {"status": "missing"}
        if ch["daohang"] < cost:
            return {"status": "no_daohang", "need": cost, "have": ch["daohang"]}
        await conn.execute(
            "UPDATE characters SET daohang=daohang-? WHERE user_id=?", (cost, user_id))
        await conn.execute(
            "UPDATE dao_paths SET xp=xp+1 WHERE user_id=? AND path_key=?",
            (user_id, row["path_key"]))
        new_level = level + 1
        await conn.execute(
            "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
            "VALUES(?,?,?,?,?)",
            (user_id, row["path_key"], "refine", new_level, now))
        return {"status": "refine_ok", "path": CFG.path_name(row["path_key"]),
                "level": new_level, "cost": cost,
                "bonuses": CFG.bonuses_for(row["path_key"], row["rank"], new_level)}


async def switch(user_id: int, path_key: str, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    if path_key not in CFG.DAO_PATHS:
        return {"status": "bad_path"}
    async with db.transaction() as conn:
        target = await _path_row(conn, user_id, path_key)
        if not target:
            cur = await conn.execute("SELECT realm FROM characters WHERE user_id=?", (user_id,))
            ch = await cur.fetchone()
            await cur.close()
            if not ch:
                return {"status": "missing"}
            if ch["realm"] < CFG.UNLOCK_REALM:
                return {"status": "locked", "need_realm": CFG.UNLOCK_REALM}
        active = await _path_row(conn, user_id, None)
        if active and active["path_key"] == path_key:
            return {"status": "already_active"}
        last = await _last_switch_at(conn, user_id)
        if last and now - last < CFG.SWITCH_COOLDOWN_SECONDS:
            return {"status": "cooldown", "remain": CFG.SWITCH_COOLDOWN_SECONDS - (now - last)}
        cur = await conn.execute("SELECT spirit_stone FROM characters WHERE user_id=?", (user_id,))
        ch = await cur.fetchone()
        await cur.close()
        if not ch:
            return {"status": "missing"}
        if ch["spirit_stone"] < CFG.SWITCH_STONE_COST:
            return {"status": "no_stone", "need": CFG.SWITCH_STONE_COST, "have": ch["spirit_stone"]}
        if await _item_qty_conn(conn, user_id, CFG.SWITCH_TOKEN, bound=1) < 1:
            return {"status": "no_token", "item": CFG.SWITCH_TOKEN}
        await conn.execute(
            "UPDATE characters SET spirit_stone=spirit_stone-? WHERE user_id=?",
            (CFG.SWITCH_STONE_COST, user_id))
        await _consume_item_conn(conn, user_id, CFG.SWITCH_TOKEN, 1, bound=1)
        if not target:
            await conn.execute(
                "INSERT INTO dao_paths(user_id, path_key, xp, rank, active, unlocked_at) "
                "VALUES(?,?,0,0,0,?)",
                (user_id, path_key, now))
        await _set_active(conn, user_id, path_key)
        await conn.execute(
            "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
            "VALUES(?,?,?,?,?)",
            (user_id, path_key, "switch", 0, now))
        return {"status": "ok", "path": CFG.path_name(path_key), "cost": CFG.SWITCH_STONE_COST}


async def _path_row(conn, user_id: int, path_key: str | None):
    if path_key is None:
        cur = await conn.execute(
            "SELECT * FROM dao_paths WHERE user_id=? AND active=1 LIMIT 1",
            (user_id,))
    else:
        cur = await conn.execute(
            "SELECT * FROM dao_paths WHERE user_id=? AND path_key=?",
            (user_id, path_key))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _last_switch_at(conn, user_id: int) -> int:
    cur = await conn.execute(
        "SELECT created_at FROM path_events WHERE user_id=? AND event_type='switch' "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return int(row["created_at"]) if row else 0


async def _item_qty_conn(conn, user_id: int, key: str, bound: int | None = None) -> int:
    if bound is None:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS qty FROM inventory WHERE user_id=? AND item_key=?",
            (user_id, key))
    else:
        cur = await conn.execute(
            "SELECT qty FROM inventory WHERE user_id=? AND item_key=? AND bound=?",
            (user_id, key, int(bool(bound))))
    row = await cur.fetchone()
    await cur.close()
    return row["qty"] if row else 0


async def _consume_item_conn(conn, user_id: int, key: str, qty: int, bound: int | None = None) -> bool:
    if qty <= 0:
        return True
    if await _item_qty_conn(conn, user_id, key, bound) < qty:
        return False
    bounds = [int(bool(bound))] if bound is not None else [1, 0]
    left = qty
    for b in bounds:
        if left <= 0:
            break
        cur = await conn.execute(
            "SELECT qty FROM inventory WHERE user_id=? AND item_key=? AND bound=?",
            (user_id, key, b))
        row = await cur.fetchone()
        await cur.close()
        if not row or row["qty"] <= 0:
            continue
        used = min(left, row["qty"])
        await conn.execute(
            "UPDATE inventory SET qty=qty-? WHERE user_id=? AND item_key=? AND bound=?",
            (used, user_id, key, b))
        left -= used
    return True


async def _set_active(conn, user_id: int, path_key: str):
    await conn.execute("UPDATE dao_paths SET active=0 WHERE user_id=?", (user_id,))
    await conn.execute(
        "UPDATE dao_paths SET active=1 WHERE user_id=? AND path_key=?",
        (user_id, path_key))


def _format_row(row) -> dict:
    return {
        "user_id": row["user_id"],
        "path_key": row["path_key"],
        "name": CFG.path_name(row["path_key"]),
        "xp": row["xp"],
        "rank": row["rank"],
        "rank_name": CFG.rank_name(row["rank"]),
        "refine": row["xp"],
        "active": bool(row["active"]),
        "unlocked_at": row["unlocked_at"],
        "bonuses": CFG.bonuses_for(row["path_key"], row["rank"], row["xp"]),
    }
