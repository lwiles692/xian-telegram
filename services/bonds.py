from __future__ import annotations

"""师徒 / 道侣关系服务（spec-v3 §4 / M3）。"""

import logging
import sqlite3
import time

from config import bonds as CFG
from config import realms as R
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
    gate = await _mentor_realm_gate_conn(conn, mentor_id, disciple_id)
    if gate["status"] != "ok":
        return gate
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
                                        initiator_id: int | None = None,
                                        now: int = None) -> dict:
    """创建待确认拜师请求；完整双向确认流程由 T3.2 handler 接入。"""
    now = _now(now)
    initiator_id = mentor_id if initiator_id is None else int(initiator_id)
    if initiator_id not in (mentor_id, disciple_id):
        return {"status": "forbidden"}
    async with db.transaction() as conn:
        check = await _can_start_mentor_request_conn(conn, mentor_id, disciple_id, now)
        if check["status"] != "ok":
            return check
        try:
            cur = await conn.execute(
                "INSERT INTO social_bonds("
                "kind, a_id, b_id, initiator_id, status, created_at, expires_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (CFG.KIND_MENTOR, mentor_id, disciple_id, initiator_id, CFG.STATUS_PENDING,
                 now, now + CFG.PENDING_EXPIRE_SECONDS, now))
        except sqlite3.IntegrityError:
            return {"status": "already_has_mentor"}
        bond_id = cur.lastrowid
        await cur.close()
    return {"status": "ok", "bond_id": int(bond_id),
            "mentor_id": mentor_id, "disciple_id": disciple_id}


async def confirm_pending_mentor_request(bond_id: int, confirmer_id: int,
                                         now: int = None) -> dict:
    """待确认拜师帖由另一方确认后生效；发起者不可自证。"""
    now = _now(now)
    async with db.transaction() as conn:
        bond = await _bond_row_conn(conn, bond_id)
        if not bond:
            return {"status": "not_found"}
        if bond["kind"] != CFG.KIND_MENTOR:
            return {"status": "bad_kind"}
        if bond["status"] != CFG.STATUS_PENDING:
            return {"status": "not_pending", "bond_status": bond["status"]}
        if int(bond["expires_at"] or 0) and int(bond["expires_at"]) <= now:
            await _mark_bond_status_conn(conn, bond_id, CFG.STATUS_EXPIRED, now)
            return {"status": "expired"}
        if confirmer_id not in (bond["a_id"], bond["b_id"]):
            return {"status": "forbidden"}
        if bond["initiator_id"] is not None and confirmer_id == bond["initiator_id"]:
            return {"status": "need_counterparty"}
        gate = await _can_activate_mentor_bond_conn(conn, bond, now)
        if gate["status"] != "ok":
            return gate
        cur = await conn.execute(
            "UPDATE social_bonds SET status=?, activated_at=?, confirmed_at=?, "
            "active_days=0, last_active_day=NULL, updated_at=? "
            "WHERE id=? AND status=?",
            (CFG.STATUS_ACTIVE, now, now, now, bond_id, CFG.STATUS_PENDING))
        changed = cur.rowcount
        await cur.close()
        if not changed:
            return {"status": "not_pending", "bond_status": CFG.STATUS_ACTIVE}
    return {"status": "ok", "bond_id": int(bond_id),
            "mentor_id": bond["a_id"], "disciple_id": bond["b_id"]}


async def decline_pending_mentor_request(bond_id: int, user_id: int,
                                         now: int = None) -> dict:
    """拒绝 pending 不进入冷却；后续可立即重发。"""
    now = _now(now)
    async with db.transaction() as conn:
        bond = await _bond_row_conn(conn, bond_id)
        if not bond:
            return {"status": "not_found"}
        if bond["kind"] != CFG.KIND_MENTOR:
            return {"status": "bad_kind"}
        if user_id not in (bond["a_id"], bond["b_id"]):
            return {"status": "forbidden"}
        if bond["status"] != CFG.STATUS_PENDING:
            return {"status": "not_pending", "bond_status": bond["status"]}
        await _mark_bond_status_conn(conn, bond_id, CFG.STATUS_DECLINED, now)
    return {"status": "ok", "bond_id": int(bond_id)}


async def dissolve_active_bond(bond_id: int, user_id: int, now: int = None) -> dict:
    """任一方可单方解除 active 关系；双方进入 7 日冷却。"""
    now = _now(now)
    async with db.transaction() as conn:
        bond = await _bond_row_conn(conn, bond_id)
        if not bond:
            return {"status": "not_found"}
        if user_id not in (bond["a_id"], bond["b_id"]):
            return {"status": "forbidden"}
        if bond["status"] != CFG.STATUS_ACTIVE:
            return {"status": "not_active", "bond_status": bond["status"]}
        cur = await conn.execute(
            "UPDATE social_bonds SET status=?, dissolved_at=?, updated_at=? "
            "WHERE id=? AND status=?",
            (CFG.STATUS_DISSOLVED, now, now, bond_id, CFG.STATUS_ACTIVE))
        changed = cur.rowcount
        await cur.close()
        if not changed:
            return {"status": "not_active", "bond_status": CFG.STATUS_DISSOLVED}
    return {"status": "ok", "bond_id": int(bond_id),
            "cooldown_until": now + CFG.DISSOLVE_COOLDOWN_SECONDS}


async def _bond_row_conn(conn, bond_id: int):
    cur = await conn.execute("SELECT * FROM social_bonds WHERE id=?", (bond_id,))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _mark_bond_status_conn(conn, bond_id: int, status: str, now: int) -> None:
    cur = await conn.execute(
        "UPDATE social_bonds SET status=?, updated_at=? WHERE id=?",
        (status, now, bond_id))
    await cur.close()


async def _mentor_realm_gate_conn(conn, mentor_id: int, disciple_id: int) -> dict:
    cur = await conn.execute(
        "SELECT user_id, realm, stage FROM characters WHERE user_id IN (?,?)",
        (mentor_id, disciple_id))
    rows = await cur.fetchall()
    await cur.close()
    by_id = {row["user_id"]: row for row in rows}
    mentor = by_id.get(mentor_id)
    disciple = by_id.get(disciple_id)
    if not mentor or not disciple:
        return {"status": "missing"}
    if int(mentor["realm"]) < CFG.MENTOR_MIN_REALM:
        return {"status": "mentor_realm_low", "need_realm": CFG.MENTOR_MIN_REALM}
    if int(disciple["realm"]) > CFG.DISCIPLE_MAX_REALM:
        return {"status": "disciple_realm_high", "max_realm": CFG.DISCIPLE_MAX_REALM}
    if int(disciple["realm"]) == CFG.DISCIPLE_MAX_REALM:
        max_stage = R.num_stages(CFG.DISCIPLE_MAX_REALM) - 1
        if int(disciple["stage"]) > max_stage:
            return {"status": "disciple_realm_high", "max_realm": CFG.DISCIPLE_MAX_REALM}
    return {"status": "ok"}


async def _can_activate_mentor_bond_conn(conn, bond, now: int) -> dict:
    gate = await _mentor_realm_gate_conn(conn, bond["a_id"], bond["b_id"])
    if gate["status"] != "ok":
        return gate
    for user_id in (bond["a_id"], bond["b_id"]):
        until = await _cooldown_until_conn(conn, user_id, now)
        if until is not None:
            return {"status": "cooldown", "user_id": user_id,
                    "cooldown_until": until, "until": until}
    cur = await conn.execute(
        "SELECT id, a_id FROM social_bonds "
        "WHERE kind=? AND b_id=? AND status=? AND id<>? LIMIT 1",
        (CFG.KIND_MENTOR, bond["b_id"], CFG.STATUS_ACTIVE, bond["id"]))
    existing = await cur.fetchone()
    await cur.close()
    if existing:
        return {"status": "already_has_mentor",
                "mentor_id": existing["a_id"], "bond_status": CFG.STATUS_ACTIVE}
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM social_bonds "
        "WHERE kind=? AND a_id=? AND status=? AND id<>?",
        (CFG.KIND_MENTOR, bond["a_id"], CFG.STATUS_ACTIVE, bond["id"]))
    row = await cur.fetchone()
    await cur.close()
    if int(row["n"] or 0) >= CFG.MAX_ACTIVE_DISCIPLES:
        return {"status": "too_many", "limit": CFG.MAX_ACTIVE_DISCIPLES}
    return {"status": "ok"}
