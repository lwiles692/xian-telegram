import random

import pytest
import pytest_asyncio

from config import daohang as DCFG
from config import realms as R
from config import bosses
from models import db
from services import character
from services import dungeon as dungeon_service
from services import explore as explore_service
from services import world_boss


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "regular-daohang.db"))
    try:
        yield
    finally:
        await db.close_db()


def _win(player, mob, **kwargs):
    return {"winner": player, "log": ["胜"], "a_hp": player.hp, "d_hp": 0, "reason": "defeat"}


@pytest.mark.asyncio
async def test_yuanying_explore_grants_regular_daohang_and_event(temp_db, monkeypatch):
    uid = 9601
    await character.create(uid, "explore-dao")
    await character.set_progress(uid, 3, 0, 0)
    monkeypatch.setattr(explore_service, "simulate", _win)

    res = await explore_service._resolve(
        uid, "上古战场", seed=1, now=1000, rng=random.Random(1),
        n_enc=1, is_boss=False, finish_at=1000)
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    event = await db.fetchone(
        "SELECT event_type, amount FROM path_events WHERE user_id=? AND event_type='explore_regular'",
        (uid,))

    assert res["status"] == "ok"
    assert res["reward"]["daohang"] == DCFG.EXPLORE_DAOHANG_BY_DIFFICULTY["易"]
    assert row["daohang"] == res["reward"]["daohang"]
    assert event["amount"] == res["reward"]["daohang"]


@pytest.mark.asyncio
async def test_jindan_explore_does_not_grant_regular_daohang(temp_db, monkeypatch):
    uid = 9602
    await character.create(uid, "jindan")
    await character.set_progress(uid, 2, 0, 0)
    monkeypatch.setattr(explore_service, "simulate", _win)

    res = await explore_service._resolve(
        uid, "万妖岭", seed=1, now=1000, rng=random.Random(1),
        n_enc=1, is_boss=False, finish_at=1000)
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    events = await db.fetchall("SELECT * FROM path_events WHERE user_id=?", (uid,))

    assert res["status"] == "ok"
    assert res["reward"]["daohang"] == 0
    assert row["daohang"] == 0
    assert events == []


@pytest.mark.asyncio
async def test_yuanying_dungeon_grants_regular_daohang_by_layers(temp_db, monkeypatch):
    uid = 9603
    await character.create(uid, "dungeon-dao")
    await character.set_progress(uid, 3, 0, 0)
    monkeypatch.setattr(dungeon_service, "simulate", _win)

    res = await dungeon_service._resolve(
        uid, "tianxu", seed=1, now=1000, rng=random.Random(1), finish_at=1000)
    expected = DCFG.DUNGEON_DAOHANG_PER_LAYER * res["layers"] + DCFG.DUNGEON_CLEAR_BONUS
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    event = await db.fetchone(
        "SELECT amount FROM path_events WHERE user_id=? AND event_type='dungeon_regular'",
        (uid,))

    assert res["cleared"] == res["layers"]
    assert res["reward"]["daohang"] == expected
    assert row["daohang"] == expected
    assert event["amount"] == expected


@pytest.mark.asyncio
async def test_regular_daohang_weekly_cap_is_shared(temp_db):
    uid = 9604
    await character.create(uid, "cap")
    await character.set_progress(uid, 3, 0, 0)

    first = await character.grant_regular_daohang(
        uid, DCFG.REGULAR_WEEKLY_CAP + 10, "test_regular", now=1000)
    second = await character.grant_regular_daohang(uid, 5, "test_regular", now=1001)
    row = await db.fetchone(
        "SELECT daohang FROM characters WHERE user_id=?", (uid,))
    weekly = await db.fetchone(
        "SELECT regular_daohang FROM weekly_activity WHERE user_id=?", (uid,))

    assert first == DCFG.REGULAR_WEEKLY_CAP
    assert second == 0
    assert row["daohang"] == DCFG.REGULAR_WEEKLY_CAP
    assert weekly["regular_daohang"] == DCFG.REGULAR_WEEKLY_CAP


@pytest.mark.asyncio
async def test_yuanying_world_boss_challenge_and_rank_grant_daohang(temp_db, monkeypatch):
    original = dict(bosses.WORLD_BOSSES["yuanying"])
    bosses.WORLD_BOSSES["yuanying"]["total_hp"] = 1
    bosses.WORLD_BOSSES["yuanying"]["stone_pool"] = 100
    uid = 9605

    def win_boss(player, mob, **kwargs):
        return {"winner": player, "log": ["胜"], "a_hp": player.hp, "d_hp": 0, "reason": "defeat"}

    try:
        await character.create(uid, "boss-dao")
        await character.set_progress(uid, 3, 0, 0)
        await db.execute(
            "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
            (200, 1000, uid))
        monkeypatch.setattr(world_boss, "simulate", win_boss)

        res = await world_boss.challenge(-9605, uid, now=1000)
        row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
        events = await db.fetchall(
            "SELECT event_type, amount FROM path_events WHERE user_id=? ORDER BY id",
            (uid,))

        assert res["status"] == "ok"
        assert res["defeated"] is True
        assert res["daohang"] == DCFG.WORLD_BOSS_CHALLENGE_DAOHANG
        assert res["rewards"][0]["daohang"] == DCFG.WORLD_BOSS_RANK_DAOHANG[0]
        assert row["daohang"] == res["daohang"] + res["rewards"][0]["daohang"]
        assert [event["event_type"] for event in events] == [
            "world_boss_challenge", "world_boss_rank"]
    finally:
        bosses.WORLD_BOSSES["yuanying"] = original
