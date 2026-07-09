from __future__ import annotations

import pytest
import pytest_asyncio

from config import realms as R
from models import db
from services import character


DAY = 24 * 3600


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "onboarding.db"))
    yield
    await db.close_db()


async def _设注册时辰(user_id: int, created_at: int):
    await db.execute(
        "UPDATE characters SET created_at=?, stamina_at=? WHERE user_id=?",
        (created_at, created_at, user_id))
    await db.execute(
        "UPDATE users SET created_at=?, last_seen_at=? WHERE tg_user_id=?",
        (created_at, created_at, user_id))


async def _备好师徒(mentor_id: int, disciple_id: int, now: int) -> int:
    from services import bonds

    await character.create(mentor_id, f"引路师尊{mentor_id}")
    await character.set_progress(mentor_id, 3, 0, 0)
    await character.create(disciple_id, f"新入门{disciple_id}")
    await character.set_progress(disciple_id, 1, R.num_stages(1) - 1, 0)
    pending = await bonds.create_pending_mentor_request(
        mentor_id, disciple_id, initiator_id=mentor_id, now=now)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_mentor_request(
        pending["bond_id"], confirmer_id=disciple_id, now=now + 1)
    assert confirmed["status"] == "ok"
    return pending["bond_id"]


@pytest.mark.asyncio
async def test_七日引导_按注册天数解锁且过期隐藏(temp_db):
    from services import quests

    uid = 6101
    start = 10_000
    await character.create(uid, "初入山门")
    await _设注册时辰(uid, start)

    day_one = await quests.list_status(uid, now=start)
    day_five = await quests.list_status(uid, now=start + 4 * DAY)
    expired = await quests.list_status(uid, now=start + 7 * DAY)

    day_one_keys = {q["key"] for q in day_one["quests"]}
    day_five_keys = {q["key"] for q in day_five["quests"]}
    expired_keys = {q["key"] for q in expired["quests"]}

    assert {"onboarding_daily", "onboarding_explore"} <= day_one_keys
    assert "onboarding_market" not in day_one_keys
    assert "onboarding_market" in day_five_keys
    assert not any(key.startswith("onboarding_") for key in expired_keys)


@pytest.mark.asyncio
async def test_七日引导_签到事件领奖给绑定物与精力(temp_db):
    from services import daily, market, quests

    uid = 6201
    start = 20_000
    await character.create(uid, "领路新修")
    await _设注册时辰(uid, start)
    await db.execute("UPDATE characters SET stamina=0, stamina_at=? WHERE user_id=?", (start, uid))
    before = await db.fetchone(
        "SELECT spirit_stone, stamina FROM characters WHERE user_id=?", (uid,))

    checked = await daily.checkin(uid, now=start)
    state = await quests.list_status(uid, now=start)
    daily_quest = next(q for q in state["quests"] if q["key"] == "onboarding_daily")
    claimed = await quests.claim(uid, "onboarding_daily", now=start)
    after = await db.fetchone(
        "SELECT spirit_stone, stamina FROM characters WHERE user_id=?", (uid,))

    assert checked["status"] == "ok"
    assert daily_quest["ready"] is True
    assert claimed["status"] == "ok"
    assert after["spirit_stone"] == before["spirit_stone"] + checked["stone"] + 80
    assert after["stamina"] == before["stamina"] + 20
    assert await character.item_qty(uid, "疗伤丹", bound=1) == 1
    assert await character.item_qty(uid, "疗伤丹", bound=0) == 0
    listed = await market.create_listing(uid, "疗伤丹", 1, 10, now=start + 1)
    assert listed["status"] == "no_item"
    assert "绑定疗伤丹×1" in quests.reward_text(claimed["reward"])


@pytest.mark.asyncio
async def test_七日引导_既有角色不可补领(temp_db):
    from services import game_events, quests

    uid = 6301
    start = 30_000
    await character.create(uid, "旧档道友")
    await _设注册时辰(uid, start)
    later = start + 8 * DAY

    async with db.transaction() as conn:
        await game_events.emit_conn(conn, uid, "daily.checkin", {"amount": 1}, now=later)
    state = await quests.list_status(uid, now=later)
    claimed = await quests.claim(uid, "onboarding_daily", now=later)
    progress = await db.fetchall(
        "SELECT * FROM quest_progress WHERE user_id=? AND quest_key LIKE 'onboarding_%'",
        (uid,))

    assert not any(q["key"].startswith("onboarding_") for q in state["quests"])
    assert claimed["status"] == "not_open"
    assert progress == []


@pytest.mark.asyncio
async def test_七日引导_徒弟领奖触发师徒双方小额联动奖励(temp_db):
    from services import game_events, quests

    start = 40_000
    mentor_id, disciple_id = 6401, 6501
    await _备好师徒(mentor_id, disciple_id, start - 100)
    await _设注册时辰(disciple_id, start)
    before_mentor = await character.get(mentor_id)
    before_disciple = await character.get(disciple_id)

    async with db.transaction() as conn:
        await game_events.emit_conn(conn, disciple_id, "explore.win", {"amount": 1}, now=start)
    claimed = await quests.claim(disciple_id, "onboarding_explore", now=start)
    duplicate = await quests.claim(disciple_id, "onboarding_explore", now=start)
    after_mentor = await character.get(mentor_id)
    after_disciple = await character.get(disciple_id)
    milestone = await db.fetchone(
        "SELECT milestone FROM bond_milestones WHERE a_id=? AND b_id=? AND milestone=?",
        (mentor_id, disciple_id, "onboarding:onboarding_explore"))
    bond = await db.fetchone("SELECT active_days FROM social_bonds WHERE b_id=?", (disciple_id,))

    assert claimed["status"] == "ok"
    assert claimed["bond_reward"]["status"] == "ok"
    assert duplicate["status"] == "claimed"
    assert after_mentor.spirit_stone == before_mentor.spirit_stone + 40
    assert after_disciple.spirit_stone == before_disciple.spirit_stone + 100 + 40
    assert await character.item_qty(disciple_id, "补灵丹", bound=1) == 1
    assert await character.item_qty(disciple_id, "疗伤丹", bound=1) == 1
    assert milestone["milestone"] == "onboarding:onboarding_explore"
    assert bond["active_days"] == 1


@pytest.mark.asyncio
async def test_七日引导_坊市与入宗事件接入任务管线(temp_db):
    from services import market, quests, sect

    start = 50_000
    market_uid = 6601
    sect_uid = 6602
    await character.create(market_uid, "试摊小修")
    await _设注册时辰(market_uid, start)
    await character.add_item(market_uid, "灵草", 1, bound=0)
    listed = await market.create_listing(market_uid, "灵草", 1, 10, now=start + 4 * DAY)
    market_state = await quests.list_status(market_uid, now=start + 4 * DAY)
    market_quest = next(q for q in market_state["quests"] if q["key"] == "onboarding_market")

    await character.create(sect_uid, "寻宗小修")
    await _设注册时辰(sect_uid, start)
    await db.execute(
        "INSERT INTO sects(name, level, contribution_pool, leader_user_id, created_at) "
        "VALUES('青云别院',1,0,9999,?)",
        (start,))
    joined = await sect.join(sect_uid, "青云别院", now=start + 5 * DAY)
    sect_state = await quests.list_status(sect_uid, now=start + 5 * DAY)
    sect_quest = next(q for q in sect_state["quests"] if q["key"] == "onboarding_sect")

    assert listed["status"] == "ok"
    assert market_quest["ready"] is True
    assert joined["status"] == "ok"
    assert sect_quest["ready"] is True
