from __future__ import annotations

import pytest
import pytest_asyncio

from config import bonds as BONDS
from models import db
from services import bonds, character, communion


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "communion.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _active_mentor_bond(mentor_id: int, disciple_id: int,
                              now: int = 1000) -> int:
    await character.create(mentor_id, f"mentor-{mentor_id}")
    await character.create(disciple_id, f"disciple-{disciple_id}")
    await character.set_progress(mentor_id, 3, 0, 0)
    pending = await bonds.create_pending_mentor_request(
        mentor_id, disciple_id, initiator_id=mentor_id, now=now + 1)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_mentor_request(
        pending["bond_id"], disciple_id, now=now + 2)
    assert confirmed["status"] == "ok"
    return confirmed["bond_id"]


@pytest.mark.asyncio
async def test_共修邀请确认后占周次并写活动窗口且结算幂等(temp_db):
    mentor_id, disciple_id = 4101, 4102
    await _active_mentor_bond(mentor_id, disciple_id)
    before_mentor = await character.get(mentor_id)
    before_disciple = await character.get(disciple_id)

    invited = await communion.invite(
        BONDS.KIND_MENTOR, mentor_id, disciple_id, now=2000)
    started = await communion.confirm(
        invited["session_id"], disciple_id, now=2000 + 60)
    usages = await db.fetchall(
        "SELECT user_id, session_id FROM communion_weekly_usage ORDER BY user_id",
        ())
    windows = await db.fetchall(
        "SELECT user_id, kind, source_key, start_at, finish_at "
        "FROM activity_windows WHERE kind=? ORDER BY user_id",
        (communion.ACTIVITY_KIND,))
    settled = await communion.complete(started["session_id"], now=started["end_at"])
    second = await communion.complete(started["session_id"], now=started["end_at"] + 1)
    after_mentor = await character.get(mentor_id)
    after_disciple = await character.get(disciple_id)

    assert invited["status"] == "ok"
    assert started["status"] == "ok"
    assert [row["user_id"] for row in usages] == [mentor_id, disciple_id]
    assert all(row["session_id"] == invited["session_id"] for row in usages)
    assert len(windows) == 2
    assert all(row["source_key"] == f"communion:{invited['session_id']}" for row in windows)
    assert all(row["start_at"] == started["start_at"] for row in windows)
    assert all(row["finish_at"] == started["end_at"] for row in windows)
    assert settled["status"] == "ok"
    assert settled["settled"] is True
    assert second["status"] == "ok"
    assert second["settled"] is False
    assert after_disciple.cultivation > before_disciple.cultivation
    assert after_mentor.daohang == before_mentor.daohang + communion.MENTOR_DAOHANG_REWARD


@pytest.mark.asyncio
async def test_共修邀请超过十分钟确认会作废(temp_db):
    mentor_id, disciple_id = 4111, 4112
    await _active_mentor_bond(mentor_id, disciple_id)

    invited = await communion.invite(
        BONDS.KIND_MENTOR, mentor_id, disciple_id, now=3000)
    expired = await communion.confirm(
        invited["session_id"], disciple_id,
        now=3000 + communion.INVITE_TTL_SECONDS + 1)
    row = await db.fetchone(
        "SELECT status FROM communion_sessions WHERE id=?",
        (invited["session_id"],))
    usages = await db.fetchall("SELECT * FROM communion_weekly_usage", ())

    assert expired["status"] == "expired"
    assert row["status"] == communion.STATUS_EXPIRED
    assert usages == []


@pytest.mark.asyncio
async def test_共修发邀前会作废过期邀请并允许重邀(temp_db):
    mentor_id, disciple_id = 4113, 4114
    await _active_mentor_bond(mentor_id, disciple_id)

    first = await communion.invite(
        BONDS.KIND_MENTOR, mentor_id, disciple_id, now=3100)
    second = await communion.invite(
        BONDS.KIND_MENTOR, mentor_id, disciple_id,
        now=3100 + communion.INVITE_TTL_SECONDS + 1)
    rows = await db.fetchall(
        "SELECT id, status FROM communion_sessions ORDER BY id",
        ())

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert [row["status"] for row in rows] == [
        communion.STATUS_EXPIRED,
        communion.STATUS_PENDING,
    ]
    assert rows[0]["id"] == first["session_id"]
    assert rows[1]["id"] == second["session_id"]


@pytest.mark.asyncio
async def test_共修每人每周跨关系只可开始一次(temp_db):
    mentor_id, disciple_id, partner_id = 4121, 4122, 4123
    await _active_mentor_bond(mentor_id, disciple_id)
    await character.create(partner_id, "partner")
    await db.execute(
        "INSERT INTO social_bonds(kind, a_id, b_id, initiator_id, status, "
        "created_at, activated_at, confirmed_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (BONDS.KIND_PARTNER, disciple_id, partner_id, disciple_id,
         BONDS.STATUS_ACTIVE, 1000, 1000, 1000, 1000))

    first = await communion.invite(
        BONDS.KIND_MENTOR, mentor_id, disciple_id, now=4000)
    started = await communion.confirm(first["session_id"], disciple_id, now=4010)
    settled = await communion.complete(started["session_id"], now=started["end_at"])
    second = await communion.invite(
        BONDS.KIND_PARTNER, disciple_id, partner_id, now=started["end_at"] + 10)

    assert started["status"] == "ok"
    assert settled["status"] == "ok"
    assert second["status"] == "weekly_used"
    assert second["user_id"] == disciple_id


@pytest.mark.asyncio
async def test_共修中途被其他活动打断则不发奖励且周次不退(temp_db):
    mentor_id, disciple_id = 4131, 4132
    await _active_mentor_bond(mentor_id, disciple_id)
    before_mentor = await character.get(mentor_id)
    before_disciple = await character.get(disciple_id)

    invited = await communion.invite(
        BONDS.KIND_MENTOR, mentor_id, disciple_id, now=5000)
    started = await communion.confirm(invited["session_id"], disciple_id, now=5010)
    await db.execute(
        "INSERT INTO activity_windows(user_id, kind, source_key, start_at, finish_at) "
        "VALUES(?,?,?,?,?)",
        (disciple_id, "explore", "后山", started["start_at"] + 60, started["start_at"] + 120))
    interrupted = await communion.complete(started["session_id"], now=started["end_at"])
    second = await communion.complete(started["session_id"], now=started["end_at"] + 1)
    after_mentor = await character.get(mentor_id)
    after_disciple = await character.get(disciple_id)
    usages = await db.fetchall("SELECT * FROM communion_weekly_usage", ())

    assert interrupted["status"] == "interrupted"
    assert interrupted["weekly_spent"] is True
    assert second["status"] == "interrupted"
    assert len(usages) == 2
    assert after_disciple.cultivation == before_disciple.cultivation
    assert after_mentor.daohang == before_mentor.daohang
