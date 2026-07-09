from __future__ import annotations

import pytest
import pytest_asyncio

from config import weekly_events as WEEKLY
from models import db
from services import character, weekly_events


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "partner-weekly.db"))
    yield
    await db.close_db()


async def _备好角色(user_id: int, name: str):
    await character.create(user_id, name)
    await character.set_progress(user_id, 2, 0, 0)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=?, daohang=0 WHERE user_id=?",
        (WEEKLY.RUN_STAMINA_COST * 6, 1000, user_id))


async def _激活道侣(a_id: int, b_id: int, now: int):
    from config import bonds as BONDS
    from services import bonds

    await _备好角色(a_id, f"同修道友{a_id}")
    await _备好角色(b_id, f"同修道友{b_id}")
    await character.add_item(a_id, BONDS.PARTNER_TOKEN_ITEM, 1, bound=1)
    pending = await bonds.create_pending_partner_request(a_id, b_id, initiator_id=a_id, now=now)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=b_id, now=now + 1)
    assert confirmed["status"] == "ok"


@pytest.mark.asyncio
async def test_道侣周活动双人任务_双方异步完成后发奖且幂等(temp_db):
    now = 80_000
    a_id, b_id = 5801, 5802
    await _激活道侣(a_id, b_id, now)
    open_key = weekly_events.current_theme_key(now + 100)

    first = await weekly_events.run(a_id, open_key, now=now + 100)
    second = await weekly_events.run(b_id, open_key, now=now + 200)
    duplicate = await weekly_events.run(a_id, open_key, now=now + 300)

    a_char = await character.get(a_id)
    b_char = await character.get(b_id)
    rows = await db.fetchall(
        "SELECT user_id, daohang FROM weekly_activity ORDER BY user_id")
    task = await db.fetchone(
        "SELECT a_done, b_done, reward_a, reward_b, settled_at "
        "FROM partner_weekly_tasks WHERE a_id=? AND b_id=?",
        (a_id, b_id))

    assert first["status"] == "ok"
    assert first["partner_task"]["status"] == "pending"
    assert second["status"] == "ok"
    assert second["partner_task"]["status"] == "ok"
    assert second["partner_task"]["reward_a"] == WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG
    assert second["partner_task"]["reward_b"] == WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG
    assert duplicate["status"] == "ok"
    assert duplicate["partner_task"]["status"] == "done"
    assert dict(task) == {
        "a_done": 1,
        "b_done": 1,
        "reward_a": WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG,
        "reward_b": WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG,
        "settled_at": now + 200,
    }
    assert {row["user_id"]: row["daohang"] for row in rows} == {
        a_id: WEEKLY.RUN_DAOHANG_REWARD * 2 + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG,
        b_id: WEEKLY.RUN_DAOHANG_REWARD + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG,
    }
    assert a_char.daohang == WEEKLY.RUN_DAOHANG_REWARD * 2 + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG
    assert b_char.daohang == WEEKLY.RUN_DAOHANG_REWARD + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG


@pytest.mark.asyncio
async def test_道侣周活动双人任务_奖励计入活动周上限(temp_db):
    now = 90_000
    a_id, b_id = 5901, 5902
    await _激活道侣(a_id, b_id, now)
    week = weekly_events._week(now + 100)
    open_key = weekly_events.current_theme_key(now + 100)
    await db.execute(
        "INSERT INTO weekly_activity(user_id, week, runs, daohang) VALUES(?,?,0,?)",
        (a_id, week, WEEKLY.WEEKLY_DAOHANG_CAP - 10))
    await db.execute(
        "UPDATE characters SET daohang=? WHERE user_id=?",
        (WEEKLY.WEEKLY_DAOHANG_CAP - 10, a_id))

    first = await weekly_events.run(a_id, open_key, now=now + 100)
    second = await weekly_events.run(b_id, open_key, now=now + 200)
    a_char = await character.get(a_id)
    b_char = await character.get(b_id)
    task = await db.fetchone(
        "SELECT reward_a, reward_b FROM partner_weekly_tasks WHERE a_id=? AND b_id=?",
        (a_id, b_id))
    rows = await db.fetchall(
        "SELECT user_id, daohang FROM weekly_activity ORDER BY user_id")

    assert first["daohang"] == 10
    assert second["partner_task"]["status"] == "ok"
    assert task["reward_a"] == 0
    assert task["reward_b"] == WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG
    assert {row["user_id"]: row["daohang"] for row in rows} == {
        a_id: WEEKLY.WEEKLY_DAOHANG_CAP,
        b_id: WEEKLY.RUN_DAOHANG_REWARD + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG,
    }
    assert a_char.daohang == WEEKLY.WEEKLY_DAOHANG_CAP
    assert b_char.daohang == WEEKLY.RUN_DAOHANG_REWARD + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG


@pytest.mark.asyncio
async def test_道侣周活动双人任务_非活跃关系不触发(temp_db):
    from config import bonds as BONDS

    now = 100_000
    await _备好角色(6001, "拒缘道友6001")
    await _备好角色(6002, "拒缘道友6002")
    await db.execute(
        "INSERT INTO social_bonds(kind, a_id, b_id, initiator_id, status, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (BONDS.KIND_PARTNER, 6001, 6002, 6001, BONDS.STATUS_DECLINED, now, now))
    open_key = weekly_events.current_theme_key(now + 100)

    res = await weekly_events.run(6001, open_key, now=now + 100)
    task_rows = await db.fetchall("SELECT * FROM partner_weekly_tasks")

    assert res["status"] == "ok"
    assert res["partner_task"]["status"] == "no_partner"
    assert task_rows == []
