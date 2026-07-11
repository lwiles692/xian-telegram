from __future__ import annotations

import pytest
import pytest_asyncio

from config import bonds as BONDS
from config import weekly_events as WEEKLY
from models import db
from services import bonds, character, communion, settle, weekly_events


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "t.db"))
    yield
    await db.close_db()


async def _备好道侣角色(user_id: int, name: str, now: int) -> None:
    await character.create(user_id, name)
    await character.set_progress(user_id, 3, 0, 0)
    await db.execute(
        "UPDATE characters SET root_bone=0, cultivation=0, daohang=0, "
        "stamina=?, stamina_at=?, seclusion_at=NULL, "
        "last_seclusion_start=NULL, last_seclusion_end=NULL, "
        "current_hp=NULL, current_mp=NULL WHERE user_id=?",
        (WEEKLY.RUN_STAMINA_COST * 4, now, user_id))


async def _道侣镜像行(a_id: int, b_id: int):
    return await db.fetchall(
        "SELECT id, a_id, b_id, status, activated_at, confirmed_at "
        "FROM social_bonds WHERE kind=? "
        "AND ((a_id=? AND b_id=?) OR (a_id=? AND b_id=?)) "
        "ORDER BY a_id, b_id",
        (BONDS.KIND_PARTNER, a_id, b_id, b_id, a_id))


@pytest.mark.asyncio
async def test_道侣完整玩家动线_结契双修互赠周任务共修发奖(temp_db):
    a_id, b_id = 8801, 8802
    now = 1_700_000_000
    await _备好道侣角色(a_id, "并蒂道友甲", now)
    await _备好道侣角色(b_id, "并蒂道友乙", now)

    await character.add_item(a_id, BONDS.PARTNER_TOKEN_ITEM, 1, bound=1)
    pending = await bonds.create_pending_partner_request(
        a_id, b_id, initiator_id=a_id, now=now)
    confirmed = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=b_id, now=now + 60)
    rows = await _道侣镜像行(a_id, b_id)

    assert pending["status"] == "ok"
    assert confirmed["status"] == "ok"
    assert {row["id"] for row in rows} == {
        confirmed["bond_id"], confirmed["mirror_bond_id"]}
    assert {(row["a_id"], row["b_id"]) for row in rows} == {
        (a_id, b_id), (b_id, a_id)}
    assert {row["status"] for row in rows} == {BONDS.STATUS_ACTIVE}
    assert {row["activated_at"] for row in rows} == {now + 60}
    assert {row["confirmed_at"] for row in rows} == {now + 60}
    assert await character.item_qty(a_id, BONDS.PARTNER_TOKEN_ITEM, bound=1) == 0

    seclusion_at = now + 3_600
    await character.start_seclusion(b_id, now=seclusion_at)
    await character.start_seclusion(a_id, now=seclusion_at + 1_800)
    a_collected = await character.collect_seclusion(a_id, now=seclusion_at + 5_400)
    b_collected = await character.collect_seclusion(b_id, now=seclusion_at + 7_200)
    a_seclusion = await db.fetchone(
        "SELECT cultivation, last_seclusion_start, last_seclusion_end "
        "FROM characters WHERE user_id=?",
        (a_id,))
    expected_overlap = 3_600
    expected_extra = settle.partner_seclusion_extra_gain(
        3, 0, expected_overlap, root_bone=0,
        partner_pct=settle.PARTNER_SECLUSION_PCT)
    expected_gain, _ = settle.seclusion_gain_with_remainder(
        3, 0, seclusion_at + 1_800, seclusion_at + 5_400, root_bone=0,
        partner_overlap_seconds=expected_overlap,
        partner_pct=settle.PARTNER_SECLUSION_PCT)

    assert a_collected["status"] == "collected"
    assert a_collected["partner_id"] == b_id
    assert a_collected["partner_overlap_seconds"] == expected_overlap
    assert a_collected["partner_extra_cultivation"] == expected_extra
    assert a_collected["partner_extra_cultivation"] > 0
    assert a_collected["gained"] == expected_gain
    assert dict(a_seclusion) == {
        "cultivation": expected_gain,
        "last_seclusion_start": seclusion_at + 1_800,
        "last_seclusion_end": seclusion_at + 5_400,
    }
    assert b_collected["status"] == "collected"

    await character.add_item(a_id, "疗伤丹", 1, bound=1)
    gifted = await bonds.grant_daily_partner_gift(
        a_id, "疗伤丹", now=seclusion_at + 8_000)

    assert BONDS.is_partner_gift_allowed("疗伤丹") is True
    assert gifted["status"] == "ok"
    assert gifted["receiver_id"] == b_id
    assert gifted["item"] == "疗伤丹"
    assert gifted["bound"] == 1
    assert await character.item_qty(a_id, "疗伤丹", bound=1) == 0
    assert await character.item_qty(b_id, "疗伤丹", bound=1) == 1

    weekly_at = now + 20_000
    open_key = weekly_events.current_theme_key(weekly_at)
    first_weekly = await weekly_events.run(a_id, open_key, now=weekly_at)
    second_weekly = await weekly_events.run(
        b_id, open_key, now=weekly_at + WEEKLY.RUN_DURATION_SECONDS + 60)
    task = await db.fetchone(
        "SELECT a_done, b_done, reward_a, reward_b, settled_at "
        "FROM partner_weekly_tasks WHERE bond_kind=? AND a_id=? AND b_id=?",
        (BONDS.KIND_PARTNER, a_id, b_id))
    after_week_a = await character.get(a_id)
    after_week_b = await character.get(b_id)

    assert first_weekly["status"] == "ok"
    assert first_weekly["partner_task"]["status"] == "pending"
    assert second_weekly["status"] == "ok"
    assert second_weekly["partner_task"]["status"] == "ok"
    assert dict(task) == {
        "a_done": 1,
        "b_done": 1,
        "reward_a": WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG,
        "reward_b": WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG,
        "settled_at": weekly_at + WEEKLY.RUN_DURATION_SECONDS + 60,
    }
    assert after_week_a.daohang == (
        WEEKLY.RUN_DAOHANG_REWARD + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG)
    assert after_week_b.daohang == (
        WEEKLY.RUN_DAOHANG_REWARD + WEEKLY.PARTNER_WEEKLY_TASK_DAOHANG)

    communion_at = weekly_at + WEEKLY.RUN_DURATION_SECONDS * 3
    before_communion_a = await character.get(a_id)
    before_communion_b = await character.get(b_id)
    invited = await communion.invite(
        BONDS.KIND_PARTNER, a_id, b_id, now=communion_at)
    started = await communion.confirm(
        invited["session_id"], b_id, now=communion_at + 60)
    completed = await communion.complete(
        started["session_id"], now=started["end_at"])
    second_complete = await communion.complete(
        started["session_id"], now=started["end_at"] + 1)
    after_communion_a = await character.get(a_id)
    after_communion_b = await character.get(b_id)
    usages = await db.fetchall(
        "SELECT user_id, kind, session_id FROM communion_weekly_usage "
        "ORDER BY user_id")

    assert invited["status"] == "ok"
    assert started["status"] == "ok"
    assert completed["status"] == "ok"
    assert completed["settled"] is True
    assert second_complete["status"] == "ok"
    assert second_complete["settled"] is False
    assert completed["rewards"][a_id]["cultivation"] > 0
    assert completed["rewards"][b_id]["cultivation"] > 0
    assert after_communion_a.cultivation == (
        before_communion_a.cultivation
        + completed["rewards"][a_id]["cultivation"])
    assert after_communion_b.cultivation == (
        before_communion_b.cultivation
        + completed["rewards"][b_id]["cultivation"])
    assert [dict(row) for row in usages] == [
        {"user_id": a_id, "kind": BONDS.KIND_PARTNER,
         "session_id": invited["session_id"]},
        {"user_id": b_id, "kind": BONDS.KIND_PARTNER,
         "session_id": invited["session_id"]},
    ]
