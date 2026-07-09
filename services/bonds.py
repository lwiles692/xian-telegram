from __future__ import annotations

"""师徒 / 道侣关系服务（spec-v3 §4 / M3）。"""

import logging
import sqlite3
import time

from config import bonds as CFG
from config import realms as R
from models import db

log = logging.getLogger("xian.bonds")
ACTIVE_DAY_TZ_OFFSET_SECONDS = 8 * 3600


def _now(now: int = None) -> int:
    return int(time.time()) if now is None else int(now)


def _active_day(now: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(int(now) + ACTIVE_DAY_TZ_OFFSET_SECONDS))


def _week(now: int) -> str:
    return time.strftime("%Y-%W", time.localtime(int(now)))


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


async def record_disciple_activity(conn, user_id: int, now: int = None) -> dict:
    """记录徒弟当日首个前台行为；同日去重，解除后冻结（spec-v3 §8.2）。"""
    now = _now(now)
    day = _active_day(now)
    week = _week(now)
    cur = await conn.execute(
        "SELECT id, a_id, b_id, last_active_day FROM social_bonds "
        "WHERE kind=? AND b_id=? AND status=? LIMIT 1",
        (CFG.KIND_MENTOR, user_id, CFG.STATUS_ACTIVE))
    bond = await cur.fetchone()
    await cur.close()
    if not bond:
        return {"status": "ok", "recorded": False, "active_day": day}

    cur = await conn.execute(
        "INSERT OR IGNORE INTO bond_activity_days("
        "bond_kind, a_id, b_id, active_day, week, recorded_at"
        ") VALUES(?,?,?,?,?,?)",
        (CFG.KIND_MENTOR, bond["a_id"], bond["b_id"], day, week, now))
    inserted = bool(cur.rowcount)
    await cur.close()
    recorded = False
    if inserted and bond["last_active_day"] != day:
        cur = await conn.execute(
            "UPDATE social_bonds SET active_days=active_days+1, last_active_day=?, updated_at=? "
            "WHERE id=? AND status=? AND (last_active_day IS NULL OR last_active_day<>?)",
            (day, now, bond["id"], CFG.STATUS_ACTIVE, day))
        recorded = bool(cur.rowcount)
        await cur.close()
    return {"status": "ok", "recorded": recorded, "active_day": day,
            "bond_id": bond["id"], "mentor_id": bond["a_id"], "disciple_id": bond["b_id"]}


async def disciple_activity_today(conn, user_id: int, now: int = None) -> dict:
    """读取徒弟今日是否已有前台活跃；传功与活跃天数共用此判定。"""
    now = _now(now)
    day = _active_day(now)
    cur = await conn.execute(
        "SELECT id, a_id, b_id, active_days, last_active_day FROM social_bonds "
        "WHERE kind=? AND b_id=? AND status=? LIMIT 1",
        (CFG.KIND_MENTOR, user_id, CFG.STATUS_ACTIVE))
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return {"status": "no_active_bond", "active_today": False, "active_day": day}
    return {"status": "ok", "active_today": row["last_active_day"] == day,
            "active_day": day, "bond_id": row["id"], "mentor_id": row["a_id"],
            "disciple_id": row["b_id"], "active_days": row["active_days"]}


async def active_disciple_seclusion_pct_conn(conn, user_id: int) -> float:
    """active 徒弟出师前闭关效率加成；后续出师状态接入时在此统一排除。"""
    cur = await conn.execute(
        "SELECT 1 FROM social_bonds WHERE kind=? AND b_id=? AND status=? LIMIT 1",
        (CFG.KIND_MENTOR, user_id, CFG.STATUS_ACTIVE))
    row = await cur.fetchone()
    await cur.close()
    return CFG.DISCIPLE_SECLUSION_PCT if row else 0.0


async def grant_daily_mentor_transfer(mentor_id: int, disciple_id: int,
                                      now: int = None) -> dict:
    """师父每日传功：徒弟今日已前台活跃后，每对师徒每日一次。"""
    now = _now(now)
    day = _active_day(now)
    from services import character as character_service

    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT id FROM social_bonds "
            "WHERE kind=? AND a_id=? AND b_id=? AND status=? LIMIT 1",
            (CFG.KIND_MENTOR, mentor_id, disciple_id, CFG.STATUS_ACTIVE))
        bond = await cur.fetchone()
        await cur.close()
        if not bond:
            return {"status": "not_active"}

        activity = await disciple_activity_today(conn, disciple_id, now)
        if not activity["active_today"]:
            return {"status": "inactive_today", "active_day": day}

        cur = await conn.execute(
            "SELECT realm FROM characters WHERE user_id=?",
            (disciple_id,))
        disciple = await cur.fetchone()
        await cur.close()
        if not disciple:
            return {"status": "missing"}
        realm = int(disciple["realm"])
        amount = int(CFG.MENTOR_TRANSFER_CULTIVATION_BY_REALM.get(realm, 0))
        if amount <= 0:
            return {"status": "disciple_realm_high", "realm": realm}

        try:
            cur = await conn.execute(
                "INSERT INTO bond_daily_transfers("
                "bond_kind, a_id, b_id, active_day, cultivation, granted_at"
                ") VALUES(?,?,?,?,?,?)",
                (CFG.KIND_MENTOR, mentor_id, disciple_id, day, amount, now))
        except sqlite3.IntegrityError:
            return {"status": "daily_done", "active_day": day}
        await cur.close()
        await character_service._grant_reward_conn(
            conn, disciple_id, cultivation=amount)
    return {"status": "ok", "mentor_id": mentor_id, "disciple_id": disciple_id,
            "bond_id": bond["id"], "active_day": day, "cultivation": amount}


async def settle_weekly_mentor_activity(now: int = None) -> dict:
    """T3.6 师父周活跃回报：按 active 徒弟本周活跃日发道行，按周幂等。"""
    now = _now(now)
    week = _week(now)
    from services import character as character_service

    rewards = []
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT b.id, b.a_id, b.b_id, COUNT(d.active_day) AS week_active_days "
            "FROM social_bonds b "
            "JOIN bond_activity_days d "
            "ON d.bond_kind=b.kind AND d.a_id=b.a_id AND d.b_id=b.b_id AND d.week=? "
            "LEFT JOIN bond_weekly_rewards r "
            "ON r.bond_kind=b.kind AND r.a_id=b.a_id AND r.b_id=b.b_id AND r.week=? "
            "WHERE b.kind=? AND b.status=? AND r.week IS NULL "
            "GROUP BY b.id, b.a_id, b.b_id "
            "HAVING COUNT(d.active_day)>0 "
            "ORDER BY b.a_id, b.b_id",
            (week, week, CFG.KIND_MENTOR, CFG.STATUS_ACTIVE))
        rows = await cur.fetchall()
        await cur.close()
        for row in rows:
            active_days = int(row["week_active_days"] or 0)
            raw_daohang = min(
                active_days * CFG.MENTOR_WEEKLY_DAOHANG_PER_ACTIVE_DAY,
                CFG.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE,
            )
            daohang = await character_service.grant_overflow_capped_daohang_conn(
                conn, row["a_id"], raw_daohang, "mentor_weekly_activity", now)
            await conn.execute(
                "INSERT INTO bond_weekly_rewards("
                "bond_kind, a_id, b_id, week, active_days, raw_daohang, daohang, settled_at"
                ") VALUES(?,?,?,?,?,?,?,?)",
                (CFG.KIND_MENTOR, row["a_id"], row["b_id"], week, active_days,
                 raw_daohang, daohang, now))
            rewards.append({
                "bond_id": row["id"],
                "mentor_id": row["a_id"],
                "disciple_id": row["b_id"],
                "week": week,
                "active_days": active_days,
                "raw_daohang": raw_daohang,
                "daohang": daohang,
            })
    return {"status": "ok", "week": week, "settled": len(rewards), "rewards": rewards}


async def handle_disciple_breakthrough_conn(conn, disciple_id: int, target_realm: int,
                                            target_stage: int, now: int = None) -> dict:
    """徒弟突破金丹/元婴时给师父发放一次性传承里程碑奖励。"""
    now = _now(now)
    milestone = _milestone_for_target(target_realm)
    if not milestone:
        return {"status": "ignored"}
    cur = await conn.execute(
        "SELECT id, a_id, b_id FROM social_bonds "
        "WHERE kind=? AND b_id=? AND status=? LIMIT 1",
        (CFG.KIND_MENTOR, disciple_id, CFG.STATUS_ACTIVE))
    bond = await cur.fetchone()
    await cur.close()
    if not bond:
        return {"status": "no_active_bond"}
    reward = CFG.MENTOR_MILESTONE_REWARDS[milestone]
    try:
        cur = await conn.execute(
            "INSERT INTO bond_milestones(bond_kind, a_id, b_id, milestone, claimed_at) "
            "VALUES(?,?,?,?,?)",
            (CFG.KIND_MENTOR, bond["a_id"], bond["b_id"], milestone, now))
    except sqlite3.IntegrityError:
        return {"status": "already_claimed", "milestone": milestone}
    await cur.close()
    daohang = await _grant_daohang_conn(
        conn, bond["a_id"], int(reward["daohang"]), "mentor_milestone", now)
    await _emit_mentor_event_conn(
        conn, "mentor.milestone", bond["a_id"], bond["b_id"],
        {"milestone": milestone, "target_realm": target_realm,
         "target_stage": target_stage, "daohang": daohang}, now)
    return {"status": "ok", "bond_id": bond["id"], "milestone": milestone,
            "mentor_id": bond["a_id"], "disciple_id": bond["b_id"],
            "daohang": daohang}


async def graduate_mentor_bond(bond_id: int, user_id: int, now: int = None) -> dict:
    """出师：元婴初期+且活跃天数达标，双方得绑定奖励并终止 active 师徒关系。"""
    now = _now(now)
    from services import game_events

    async with db.transaction() as conn:
        bond = await _bond_row_conn(conn, bond_id)
        if not bond:
            return {"status": "not_found"}
        if bond["kind"] != CFG.KIND_MENTOR:
            return {"status": "bad_kind"}
        if user_id not in (bond["a_id"], bond["b_id"]):
            return {"status": "forbidden"}
        if bond["status"] != CFG.STATUS_ACTIVE:
            if await _has_milestone_conn(
                    conn, bond["a_id"], bond["b_id"], CFG.GRADUATION_MILESTONE):
                return {"status": "already_graduated"}
            return {"status": "not_active", "bond_status": bond["status"]}
        cur = await conn.execute(
            "SELECT realm, stage FROM characters WHERE user_id=?",
            (bond["b_id"],))
        disciple = await cur.fetchone()
        await cur.close()
        if not disciple:
            return {"status": "missing"}
        if int(disciple["realm"]) < CFG.GRADUATION_MIN_REALM:
            return {"status": "disciple_realm_low",
                    "need_realm": CFG.GRADUATION_MIN_REALM}
        active_days = int(bond["active_days"] or 0)
        if active_days < CFG.GRADUATION_ACTIVE_DAYS_REQUIRED:
            return {"status": "active_days_low",
                    "need": CFG.GRADUATION_ACTIVE_DAYS_REQUIRED,
                    "have": active_days}
        try:
            cur = await conn.execute(
                "INSERT INTO bond_milestones(bond_kind, a_id, b_id, milestone, claimed_at) "
                "VALUES(?,?,?,?,?)",
                (CFG.KIND_MENTOR, bond["a_id"], bond["b_id"],
                 CFG.GRADUATION_MILESTONE, now))
        except sqlite3.IntegrityError:
            return {"status": "already_graduated"}
        await cur.close()

        mentor_daohang = await _grant_daohang_conn(
            conn, bond["a_id"], CFG.GRADUATION_MENTOR_DAOHANG, "mentor_graduate", now)
        disciple_daohang = await _grant_daohang_conn(
            conn, bond["b_id"], CFG.GRADUATION_DISCIPLE_DAOHANG, "disciple_graduate", now)
        await _grant_bound_items_conn(conn, bond["a_id"], CFG.GRADUATION_BOUND_ITEMS)
        await _grant_bound_items_conn(conn, bond["b_id"], CFG.GRADUATION_BOUND_ITEMS)
        await _mark_bond_status_conn(conn, bond_id, CFG.STATUS_GRADUATED, now)

        graduate_count = await _graduate_count_conn(conn, bond["a_id"])
        titles = await _unlock_mentor_titles_conn(conn, bond["a_id"], graduate_count, now)
        await _emit_mentor_event_conn(
            conn, "mentor.graduate", bond["a_id"], bond["b_id"],
            {"active_days": active_days, "graduate_count": graduate_count,
             "mentor_daohang": mentor_daohang, "disciple_daohang": disciple_daohang}, now)
        for title in titles:
            await game_events.emit_conn(
                conn, bond["a_id"], "mentor.title",
                {"title": title["title"], "threshold": title["threshold"],
                 "graduate_count": graduate_count}, now)
    return {"status": "ok", "bond_id": int(bond_id),
            "mentor_id": bond["a_id"], "disciple_id": bond["b_id"],
            "active_days": active_days, "graduate_count": graduate_count,
            "mentor_daohang": mentor_daohang, "disciple_daohang": disciple_daohang,
            "items": dict(CFG.GRADUATION_BOUND_ITEMS), "titles": titles}


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


def _milestone_for_target(target_realm: int) -> str | None:
    for milestone, reward in CFG.MENTOR_MILESTONE_REWARDS.items():
        if int(reward["target_realm"]) == int(target_realm):
            return milestone
    return None


async def _has_milestone_conn(conn, mentor_id: int, disciple_id: int, milestone: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM bond_milestones "
        "WHERE bond_kind=? AND a_id=? AND b_id=? AND milestone=?",
        (CFG.KIND_MENTOR, mentor_id, disciple_id, milestone))
    row = await cur.fetchone()
    await cur.close()
    return bool(row)


async def _grant_daohang_conn(conn, user_id: int, amount: int,
                              event_type: str, now: int) -> int:
    amount = max(0, int(amount))
    if amount <= 0:
        return 0
    await conn.execute(
        "UPDATE characters SET daohang=daohang+? WHERE user_id=?",
        (amount, user_id))
    await conn.execute(
        "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
        "VALUES(?,NULL,?,?,?)",
        (user_id, event_type, amount, now))
    return amount


async def _grant_bound_items_conn(conn, user_id: int, items: dict[str, int]) -> None:
    for key, qty in items.items():
        qty = int(qty)
        if qty <= 0:
            continue
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,1,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty=qty+?",
            (user_id, key, qty, qty))


async def _graduate_count_conn(conn, mentor_id: int) -> int:
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM bond_milestones "
        "WHERE bond_kind=? AND a_id=? AND milestone=?",
        (CFG.KIND_MENTOR, mentor_id, CFG.GRADUATION_MILESTONE))
    row = await cur.fetchone()
    await cur.close()
    return int(row["n"] or 0)


async def _unlock_mentor_titles_conn(conn, mentor_id: int, graduate_count: int,
                                    now: int) -> list[dict]:
    unlocked = []
    for threshold, title in CFG.MENTOR_TITLE_THRESHOLDS:
        if graduate_count < threshold:
            continue
        key = f"mentor_graduate_{threshold}"
        try:
            cur = await conn.execute(
                "INSERT INTO bond_titles(user_id, title_key, title, threshold, unlocked_at) "
                "VALUES(?,?,?,?,?)",
                (mentor_id, key, title, threshold, now))
        except sqlite3.IntegrityError:
            continue
        await cur.close()
        unlocked.append({"title_key": key, "title": title, "threshold": threshold})
    return unlocked


async def _name_conn(conn, user_id: int) -> str:
    cur = await conn.execute("SELECT username FROM users WHERE tg_user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row["username"] if row and row["username"] else str(user_id)


async def _emit_mentor_event_conn(conn, event_type: str, mentor_id: int,
                                  disciple_id: int, payload: dict,
                                  now: int) -> None:
    from services import game_events

    mentor_name = await _name_conn(conn, mentor_id)
    disciple_name = await _name_conn(conn, disciple_id)
    await game_events.emit_conn(
        conn, mentor_id, event_type,
        {**payload, "mentor_id": mentor_id, "disciple_id": disciple_id,
         "mentor_name": mentor_name, "disciple_name": disciple_name,
         "name": mentor_name}, now)


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
