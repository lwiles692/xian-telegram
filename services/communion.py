from __future__ import annotations

"""同步共修仪式：师徒 / 道侣通用的限周协作小玩法。"""

import datetime as dt
import sqlite3
import time

from config import bonds as BONDS
from config import realms as R
from models import db
from services import activity, bonds as bonds_service, character, settle

INVITE_TTL_SECONDS = 10 * 60
DURATION_SECONDS = 30 * 60
CULTIVATION_PACKAGE_SECONDS = 3 * 3600
MENTOR_DAOHANG_REWARD = 12

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_EXPIRED = "expired"
STATUS_INTERRUPTED = "interrupted"
OPEN_STATUSES = (STATUS_PENDING, STATUS_ACTIVE)
ACTIVITY_KIND = "communion"


def _now(now: int = None) -> int:
    return int(time.time()) if now is None else int(now)


def _week(now: int) -> str:
    year, week, _ = dt.datetime.fromtimestamp(int(now)).isocalendar()
    return f"{year:04d}-{week:02d}"


def _source_key(session_id: int) -> str:
    return f"communion:{int(session_id)}"


async def invite(kind: str, initiator_id: int, target_id: int, now: int = None) -> dict:
    """发起共修邀请；pending 不占周次，确认开始时才占用双方本周次数。"""
    now = _now(now)
    kind = str(kind)
    if kind not in BONDS.BOND_KINDS:
        return {"status": "bad_kind"}
    if initiator_id == target_id:
        return {"status": "bad_target"}
    async with db.transaction() as conn:
        bond = await _active_bond_conn(conn, kind, initiator_id, target_id)
        if not bond:
            return {"status": "not_active"}
        if initiator_id not in (bond["a_id"], bond["b_id"]):
            return {"status": "forbidden"}
        ready = await _participants_ready_conn(
            conn, (bond["a_id"], bond["b_id"]), now, now + DURATION_SECONDS)
        if ready["status"] != "ok":
            return ready
        await _expire_pending_conn(conn, now)
        open_session = await _open_session_for_users_conn(conn, bond["a_id"], bond["b_id"])
        if open_session:
            return {"status": "has_open_session", "session_id": open_session["id"],
                    "session_status": open_session["status"]}
        used = await _weekly_used_conn(conn, (bond["a_id"], bond["b_id"]), _week(now))
        if used:
            return {"status": "weekly_used", "user_id": used["user_id"], "week": used["week"]}
        cur = await conn.execute(
            "INSERT INTO communion_sessions("
            "kind, bond_id, a_id, b_id, initiator_id, status, invited_at, expires_at, updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (kind, bond["id"], bond["a_id"], bond["b_id"], initiator_id,
             STATUS_PENDING, now, now + INVITE_TTL_SECONDS, now))
        session_id = int(cur.lastrowid)
        await cur.close()
    return {"status": "ok", "session_id": session_id, "kind": kind,
            "a_id": bond["a_id"], "b_id": bond["b_id"],
            "expires_at": now + INVITE_TTL_SECONDS}


async def confirm(session_id: int, user_id: int, now: int = None) -> dict:
    """被邀请方确认后同步开始，并登记双方本周共修名额。"""
    now = _now(now)
    async with db.transaction() as conn:
        session = await _session_conn(conn, session_id)
        if not session:
            return {"status": "not_found"}
        if session["status"] == STATUS_EXPIRED:
            return {"status": "expired"}
        if session["status"] == STATUS_ACTIVE:
            return _active_payload(session)
        if session["status"] in (STATUS_COMPLETED, STATUS_INTERRUPTED):
            return {"status": session["status"], "session_id": int(session_id)}
        if session["status"] != STATUS_PENDING:
            return {"status": "bad_status", "session_status": session["status"]}
        if int(session["expires_at"]) < now:
            await _mark_status_conn(conn, session_id, STATUS_EXPIRED, now)
            return {"status": "expired"}
        if user_id not in (session["a_id"], session["b_id"]):
            return {"status": "forbidden"}
        if user_id == session["initiator_id"]:
            return {"status": "need_counterparty"}
        bond = await _active_bond_conn(conn, session["kind"], session["a_id"], session["b_id"])
        if not bond or int(bond["id"]) != int(session["bond_id"]):
            return {"status": "not_active"}
        ready = await _participants_ready_conn(
            conn, (session["a_id"], session["b_id"]), now, now + DURATION_SECONDS)
        if ready["status"] != "ok":
            return ready
        week = _week(now)
        used = await _weekly_used_conn(conn, (session["a_id"], session["b_id"]), week)
        if used:
            return {"status": "weekly_used", "user_id": used["user_id"], "week": used["week"]}
        finish_at = now + DURATION_SECONDS
        try:
            await _claim_week_conn(conn, session["a_id"], week, session_id, session["kind"], now)
            await _claim_week_conn(conn, session["b_id"], week, session_id, session["kind"], now)
        except sqlite3.IntegrityError:
            return {"status": "weekly_used", "week": week}
        source_key = _source_key(session_id)
        await activity.record_window(session["a_id"], ACTIVITY_KIND, source_key, now, finish_at, conn=conn)
        await activity.record_window(session["b_id"], ACTIVITY_KIND, source_key, now, finish_at, conn=conn)
        await conn.execute(
            "UPDATE communion_sessions SET status=?, confirmer_id=?, start_at=?, end_at=?, updated_at=? "
            "WHERE id=? AND status=?",
            (STATUS_ACTIVE, user_id, now, finish_at, now, session_id, STATUS_PENDING))
        session = await _session_conn(conn, session_id)
    return _active_payload(session)


async def expire_pending(now: int = None) -> dict:
    """批量作废超时未确认的共修邀请。"""
    now = _now(now)
    async with db.transaction() as conn:
        expired = await _expire_pending_conn(conn, now)
    return {"status": "ok", "expired": expired}


async def complete(session_id: int, now: int = None) -> dict:
    """结算共修；completed/interrupted 均幂等返回，绝不重复发奖。"""
    now = _now(now)
    async with db.transaction() as conn:
        session = await _session_conn(conn, session_id)
        if not session:
            return {"status": "not_found"}
        if session["status"] == STATUS_COMPLETED:
            return {"status": "ok", "session_id": int(session_id), "settled": False,
                    "completed": True}
        if session["status"] == STATUS_INTERRUPTED:
            return {"status": "interrupted", "session_id": int(session_id), "settled": False}
        if session["status"] == STATUS_PENDING:
            if int(session["expires_at"]) < now:
                await _mark_status_conn(conn, session_id, STATUS_EXPIRED, now)
                return {"status": "expired"}
            return {"status": "not_started"}
        if session["status"] != STATUS_ACTIVE:
            return {"status": "bad_status", "session_status": session["status"]}
        if int(session["end_at"]) > now:
            return {"status": "not_ready", "end_at": int(session["end_at"])}
        interrupted = await _has_interrupting_window_conn(conn, session)
        if interrupted:
            await conn.execute(
                "UPDATE communion_sessions SET status=?, completed_at=?, updated_at=? WHERE id=?",
                (STATUS_INTERRUPTED, now, now, session_id))
            return {"status": "interrupted", "session_id": int(session_id),
                    "settled": True, "weekly_spent": True}
        rewards = await _grant_rewards_conn(conn, session, now)
        await conn.execute(
            "UPDATE communion_sessions SET status=?, completed_at=?, updated_at=? WHERE id=?",
            (STATUS_COMPLETED, now, now, session_id))
    return {"status": "ok", "session_id": int(session_id), "settled": True,
            "completed": True, "rewards": rewards}


async def _active_bond_conn(conn, kind: str, user_a: int, user_b: int):
    cur = await conn.execute(
        "SELECT id, kind, a_id, b_id FROM social_bonds "
        "WHERE kind=? AND status=? "
        "AND ((a_id=? AND b_id=?) OR (a_id=? AND b_id=?)) LIMIT 1",
        (kind, BONDS.STATUS_ACTIVE, user_a, user_b, user_b, user_a))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _session_conn(conn, session_id: int):
    cur = await conn.execute("SELECT * FROM communion_sessions WHERE id=?", (int(session_id),))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _participants_ready_conn(conn, user_ids: tuple[int, int],
                                   start_at: int, end_at: int) -> dict:
    cur = await conn.execute(
        "SELECT user_id, realm, stage, current_hp FROM characters WHERE user_id IN (?,?)",
        (user_ids[0], user_ids[1]))
    rows = await cur.fetchall()
    await cur.close()
    by_id = {int(row["user_id"]): row for row in rows}
    for user_id in user_ids:
        row = by_id.get(int(user_id))
        if not row:
            return {"status": "missing", "user_id": int(user_id)}
        if row["current_hp"] is not None:
            base_hp = R.base_stats(int(row["realm"]), int(row["stage"]))["hp"]
            if int(row["current_hp"]) <= int(base_hp * settle.HP_FLOOR_PCT):
                return {"status": "wounded", "user_id": int(user_id)}
    busy = await _busy_users_conn(conn, user_ids, start_at, end_at)
    if busy:
        return {"status": "busy", "user_id": busy[0]}
    return {"status": "ok"}


async def _busy_users_conn(conn, user_ids: tuple[int, int], start_at: int, end_at: int,
                           source_key: str | None = None) -> list[int]:
    params = [user_ids[0], user_ids[1], int(start_at), int(end_at)]
    exclusion = ""
    if source_key:
        exclusion = "AND NOT (kind=? AND source_key=?) "
        params.extend([ACTIVITY_KIND, source_key])
    cur = await conn.execute(
        "SELECT DISTINCT user_id FROM activity_windows "
        "WHERE user_id IN (?,?) AND finish_at>? AND start_at<? "
        f"{exclusion}"
        "ORDER BY user_id",
        tuple(params))
    rows = await cur.fetchall()
    await cur.close()
    return [int(row["user_id"]) for row in rows]


async def _open_session_for_users_conn(conn, a_id: int, b_id: int):
    cur = await conn.execute(
        "SELECT id, status FROM communion_sessions "
        "WHERE status IN (?,?) AND (a_id IN (?,?) OR b_id IN (?,?)) "
        "ORDER BY id DESC LIMIT 1",
        (STATUS_PENDING, STATUS_ACTIVE, a_id, b_id, a_id, b_id))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _expire_pending_conn(conn, now: int) -> int:
    cur = await conn.execute(
        "UPDATE communion_sessions SET status=?, updated_at=? "
        "WHERE status=? AND expires_at<?",
        (STATUS_EXPIRED, now, STATUS_PENDING, now))
    expired = int(cur.rowcount or 0)
    await cur.close()
    return expired


async def _weekly_used_conn(conn, user_ids: tuple[int, int], week: str):
    cur = await conn.execute(
        "SELECT user_id, week, session_id FROM communion_weekly_usage "
        "WHERE week=? AND user_id IN (?,?) ORDER BY user_id LIMIT 1",
        (week, user_ids[0], user_ids[1]))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _claim_week_conn(conn, user_id: int, week: str, session_id: int,
                           kind: str, now: int) -> None:
    await conn.execute(
        "INSERT INTO communion_weekly_usage(user_id, week, session_id, kind, used_at) "
        "VALUES(?,?,?,?,?)",
        (user_id, week, int(session_id), kind, now))


async def _mark_status_conn(conn, session_id: int, status: str, now: int) -> None:
    await conn.execute(
        "UPDATE communion_sessions SET status=?, updated_at=? WHERE id=?",
        (status, now, int(session_id)))


def _active_payload(session) -> dict:
    return {"status": "ok", "session_id": int(session["id"]), "active": True,
            "start_at": int(session["start_at"]), "end_at": int(session["end_at"]),
            "kind": session["kind"], "a_id": session["a_id"], "b_id": session["b_id"]}


async def _has_interrupting_window_conn(conn, session) -> bool:
    busy = await _busy_users_conn(
        conn, (session["a_id"], session["b_id"]),
        int(session["start_at"]), int(session["end_at"]), _source_key(session["id"]))
    return bool(busy)


async def _grant_rewards_conn(conn, session, now: int) -> dict:
    rows = await _character_rows_conn(conn, (session["a_id"], session["b_id"]))
    rewards: dict[int, dict] = {}
    if session["kind"] == BONDS.KIND_MENTOR:
        disciple_id = int(session["b_id"])
        mentor_id = int(session["a_id"])
        cult = _cultivation_reward(rows[disciple_id])
        await character._grant_reward_conn(conn, disciple_id, cultivation=cult)
        daohang = await _grant_daohang_conn(conn, mentor_id, MENTOR_DAOHANG_REWARD, now)
        rewards[disciple_id] = {"cultivation": cult}
        rewards[mentor_id] = {"daohang": daohang}
        await bonds_service.record_disciple_activity(conn, disciple_id, now)
        return rewards
    for user_id in (int(session["a_id"]), int(session["b_id"])):
        cult = _cultivation_reward(rows[user_id])
        await character._grant_reward_conn(conn, user_id, cultivation=cult)
        rewards[user_id] = {"cultivation": cult}
    return rewards


async def _character_rows_conn(conn, user_ids: tuple[int, int]) -> dict[int, object]:
    cur = await conn.execute(
        "SELECT user_id, realm, stage FROM characters WHERE user_id IN (?,?)",
        (user_ids[0], user_ids[1]))
    rows = await cur.fetchall()
    await cur.close()
    return {int(row["user_id"]): row for row in rows}


def _cultivation_reward(row) -> int:
    return max(1, settle.seclusion_gain(
        int(row["realm"]), int(row["stage"]), 0, CULTIVATION_PACKAGE_SECONDS))


async def _grant_daohang_conn(conn, user_id: int, amount: int, now: int) -> int:
    amount = max(0, int(amount))
    if amount <= 0:
        return 0
    await conn.execute(
        "UPDATE characters SET daohang=daohang+? WHERE user_id=?",
        (amount, user_id))
    await conn.execute(
        "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
        "VALUES(?,NULL,?,?,?)",
        (user_id, "communion_mentor", amount, now))
    return amount
