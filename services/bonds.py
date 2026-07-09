from __future__ import annotations

"""师徒 / 道侣关系服务（spec-v3 §4 / M3）。"""

import logging
import sqlite3
import time

from config import bonds as CFG
from models import db

log = logging.getLogger("xian.bonds")


def _now(now: int = None) -> int:
    return int(time.time()) if now is None else int(now)


async def expire_pending(now: int = None) -> dict:
    """把 48 小时未确认的关系请求置为 expired；declined/expired 不触发冷却。"""
    now = _now(now)
    cutoff = now - CFG.PENDING_EXPIRE_SECONDS
    async with db.transaction() as conn:
        cur = await conn.execute(
            "UPDATE social_bonds SET status=?, updated_at=? "
            "WHERE status=? AND (expires_at<=? OR (expires_at IS NULL AND created_at<=?))",
            (CFG.STATUS_EXPIRED, now, CFG.STATUS_PENDING, now, cutoff))
        expired = cur.rowcount
        await cur.close()
    return {"status": "ok", "expired": int(expired)}


async def cooldown_until(user_id: int, now: int = None) -> int | None:
    """解除关系后的 7 天冷却；只读取 dissolved，不把拒绝/超时算作冷却。"""
    now = _now(now)
    row = await db.fetchone(
        "SELECT MAX(dissolved_at) AS last_at FROM social_bonds "
        "WHERE status=? AND dissolved_at IS NOT NULL AND (a_id=? OR b_id=?)",
        (CFG.STATUS_DISSOLVED, user_id, user_id))
    return _cooldown_until_from_row(row, now)


async def _cooldown_until_conn(conn, user_id: int, now: int) -> int | None:
    cur = await conn.execute(
        "SELECT MAX(dissolved_at) AS last_at FROM social_bonds "
        "WHERE status=? AND dissolved_at IS NOT NULL AND (a_id=? OR b_id=?)",
        (CFG.STATUS_DISSOLVED, user_id, user_id))
    row = await cur.fetchone()
    await cur.close()
    return _cooldown_until_from_row(row, now)


def _cooldown_until_from_row(row, now: int) -> int | None:
    if not row or row["last_at"] is None:
        return None
    until = int(row["last_at"]) + CFG.DISSOLVE_COOLDOWN_SECONDS
    return until if until > now else None


async def can_start_mentor_request(mentor_id: int, disciple_id: int,
                                   now: int = None) -> dict:
    """T3.1 发起前置检查：冷却、徒弟占位、师父 active 徒弟上限。"""
    now = _now(now)
    async with db.transaction() as conn:
        return await _can_start_mentor_request_conn(conn, mentor_id, disciple_id, now)


async def _can_start_mentor_request_conn(conn, mentor_id: int, disciple_id: int,
                                         now: int) -> dict:
    if mentor_id == disciple_id:
        return {"status": "bad_request"}
    for user_id in (mentor_id, disciple_id):
        until = await _cooldown_until_conn(conn, user_id, now)
        if until is not None:
            return {"status": "cooldown", "user_id": user_id,
                    "cooldown_until": until, "until": until}
    cur = await conn.execute(
        "SELECT status, a_id FROM social_bonds "
        "WHERE kind=? AND b_id=? AND status IN (?,?) "
        "ORDER BY updated_at DESC LIMIT 1",
        (CFG.KIND_MENTOR, disciple_id, CFG.STATUS_PENDING, CFG.STATUS_ACTIVE))
    existing = await cur.fetchone()
    await cur.close()
    if existing:
        return {"status": "already_has_mentor",
                "mentor_id": existing["a_id"], "bond_status": existing["status"]}
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM social_bonds "
        "WHERE kind=? AND a_id=? AND status=?",
        (CFG.KIND_MENTOR, mentor_id, CFG.STATUS_ACTIVE))
    row = await cur.fetchone()
    await cur.close()
    active = int(row["n"] or 0)
    if active >= CFG.MAX_ACTIVE_DISCIPLES:
        return {"status": "too_many", "limit": CFG.MAX_ACTIVE_DISCIPLES}
    return {"status": "ok"}


async def create_pending_mentor_request(mentor_id: int, disciple_id: int,
                                        now: int = None) -> dict:
    """创建待确认拜师请求；完整双向确认流程由 T3.2 handler 接入。"""
    now = _now(now)
    async with db.transaction() as conn:
        check = await _can_start_mentor_request_conn(conn, mentor_id, disciple_id, now)
        if check["status"] != "ok":
            return check
        try:
            cur = await conn.execute(
                "INSERT INTO social_bonds(kind, a_id, b_id, status, created_at, expires_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (CFG.KIND_MENTOR, mentor_id, disciple_id, CFG.STATUS_PENDING,
                 now, now + CFG.PENDING_EXPIRE_SECONDS, now))
        except sqlite3.IntegrityError:
            return {"status": "already_has_mentor"}
        bond_id = cur.lastrowid
        await cur.close()
    return {"status": "ok", "bond_id": int(bond_id),
            "mentor_id": mentor_id, "disciple_id": disciple_id}
