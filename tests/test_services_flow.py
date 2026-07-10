from __future__ import annotations

import asyncio
import random
import time

import pytest
import pytest_asyncio

from config import realms as R
from config.items import ITEMS
from config.maps import MAPS
from models import db
from services import breakthrough, character, cultivation
from services import dungeon as dungeon_service
from services import explore as explore_service


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "xian-test.db"))
    try:
        yield
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_db_write_lock_waits_in_running_loop(temp_db):
    async with db.transaction():
        waiter = asyncio.create_task(
            db.execute(
                "INSERT OR IGNORE INTO users(tg_user_id, username, created_at) VALUES(?,?,?)",
                (9001, "waiter", 0)))
        await asyncio.sleep(0.01)
        assert not waiter.done()

    await waiter
    row = await db.fetchone("SELECT username FROM users WHERE tg_user_id=?", (9001,))
    assert row["username"] == "waiter"


@pytest.mark.asyncio
async def test_explore_blocked_during_dungeon(temp_db):
    uid = 1101
    await character.create(uid, "tester")
    started = await dungeon_service.start(uid, "lingxi")
    assert started["status"] == "started"

    res = await explore_service.start(uid, "后山")

    assert res["status"] == "busy_dungeon"
    assert await explore_service.active_run(uid) is None
    assert await dungeon_service.active_run(uid) is not None


@pytest.mark.asyncio
async def test_dungeon_blocked_during_explore(temp_db):
    uid = 1102
    await character.create(uid, "tester")
    started = await explore_service.start(uid, "后山")
    assert started["status"] == "started"

    res = await dungeon_service.start(uid, "lingxi")

    assert res["status"] == "busy_explore"
    assert await dungeon_service.active_run(uid) is None
    assert await explore_service.active_run(uid) is not None


@pytest.mark.asyncio
async def test_seclusion_can_run_during_timed_activity(temp_db):
    uid = 1103
    await character.create(uid, "tester")
    started = await explore_service.start(uid, "后山")
    assert started["status"] == "started"

    res = await cultivation.start(uid)

    assert res["status"] == "started"
    assert (await character.get(uid)).seclusion_at
    assert await explore_service.active_run(uid) is not None


@pytest.mark.asyncio
async def test_explore_can_run_during_seclusion(temp_db):
    uid = 1001
    await character.create(uid, "tester")
    await cultivation.start(uid)
    before = await character.get(uid)

    res = await explore_service.start(uid, "后山")
    after = await character.get(uid)

    assert res["status"] == "started"
    assert after.stamina == before.stamina - 10
    assert after.seclusion_at


@pytest.mark.asyncio
async def test_concurrent_explore_spends_stamina_once(temp_db):
    uid = 1002
    await character.create(uid, "tester")
    now = int(time.time())
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (10, now, uid))

    results = await asyncio.gather(
        explore_service.start(uid, "后山"),
        explore_service.start(uid, "后山"))
    statuses = sorted(r["status"] for r in results)
    after = await character.get(uid)

    assert statuses == ["pending", "started"]
    assert after.stamina == 0


@pytest.mark.asyncio
async def test_explore_uses_unbounded_player_mob_combat(temp_db, monkeypatch):
    uid = 1111
    await character.create(uid, "explorer")
    seen = []

    def fake_simulate(player, mob, **kwargs):
        seen.append(kwargs.get("max_rounds"))
        return {"winner": player, "log": ["⚔️ 道友 对阵 灵狐！", "🏆 道友 胜！"],
                "a_hp": player.hp, "d_hp": 0, "rounds": 31, "reason": "defeat"}

    monkeypatch.setattr(explore_service, "simulate", fake_simulate)

    res = await explore_service._resolve(
        uid, "后山", seed=1, now=1000, rng=random.Random(1),
        n_enc=1, is_boss=False, finish_at=1000)

    assert res["status"] == "ok"
    assert res["win"] is True
    assert seen == [None]


@pytest.mark.asyncio
async def test_dungeon_uses_unbounded_player_mob_combat(temp_db, monkeypatch):
    uid = 1112
    await character.create(uid, "delver")
    seen = []

    def fake_simulate(player, mob, **kwargs):
        seen.append(kwargs.get("max_rounds"))
        return {"winner": player, "log": ["⚔️ 道友 对阵 洞中灵狐！", "🏆 道友 胜！"],
                "a_hp": player.hp, "d_hp": 0, "rounds": 31, "reason": "defeat"}

    monkeypatch.setattr(dungeon_service, "simulate", fake_simulate)

    res = await dungeon_service._resolve(
        uid, "lingxi", seed=1, now=1000, rng=random.Random(1), finish_at=1000)

    assert res["status"] == "ok"
    assert res["win"] is True
    assert seen and all(limit is None for limit in seen)


def test_big_breakthrough_pills_drop_before_target_realm():
    for target_realm, rule in R.BIG_BREAKTHROUGH.items():
        pill = rule["pill"]
        # T0.3 先开放炼虚配置；炼虚丹物品/掉落在 T0.4 接入，物品落表后此护栏自动覆盖。
        if pill not in ITEMS:
            continue
        assert any(
            m["realm"] < target_realm and any(drop[0] == pill for drop in m["drops"])
            for m in MAPS.values()
        ), f"{pill} must drop before realm {target_realm}"
def test_huashen_pill_chain_uses_yuanying_hard_map():
    drops = {drop[0] for drop in MAPS["天魔古原"]["drops"]}
    assert MAPS["天魔古原"]["realm"] == 3
    assert {"化神丹残方", "化神丹"} <= drops


@pytest.mark.asyncio
async def test_yuanying_to_huashen_needs_pill_and_uses_shenhun_choices(temp_db, monkeypatch):
    uid = 1004
    await character.create(uid, "tester")
    last_yy = R.num_stages(3) - 1
    cost = R.advance_cost(3, last_yy)
    await character.set_progress(uid, 3, last_yy, cost)

    assert await breakthrough.try_advance(uid, now=1000) == {"status": "need_pill", "pill": "化神丹"}

    await character.add_item(uid, "化神丹", 1)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    res = await breakthrough.try_advance(uid, now=1000)

    assert res["status"] == "tribulation_choice"
    assert [choice["key"] for choice in res["choices"]] == ["focus", "artifact", "pill"]
    assert [choice["label"] for choice in res["choices"]] == ["凝神守一", "祭出护体法宝", "服大还丹"]

    res = await breakthrough.choose_tribulation_action(uid, "focus", now=1001)
    assert "神魂劫" in "".join(res["last_log"])
    assert await character.item_qty(uid, "化神丹") == 0


@pytest.mark.asyncio
async def test_huashen_tribulation_rejects_old_lightning_choice(temp_db, monkeypatch):
    uid = 1005
    await character.create(uid, "tester")
    last_yy = R.num_stages(3) - 1
    await character.set_progress(uid, 3, last_yy, R.advance_cost(3, last_yy))
    await character.add_item(uid, "化神丹", 1)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)

    assert (await breakthrough.try_advance(uid, now=1000))["status"] == "tribulation_choice"
    assert (await breakthrough.choose_tribulation_action(uid, "endure", now=1001))["status"] == "bad_action"


@pytest.mark.asyncio
async def test_concurrent_big_breakthrough_succeeds_once(temp_db, monkeypatch):
    uid = 1003
    await character.create(uid, "tester")
    last_qi = R.num_stages(0) - 1
    cost = R.advance_cost(0, last_qi)
    await character.set_progress(uid, 0, last_qi, cost)
    await character.add_item(uid, "筑基丹", 1)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)

    results = await asyncio.gather(
        breakthrough.try_advance(uid),
        breakthrough.try_advance(uid))
    statuses = [r["status"] for r in results]
    char = await character.get(uid)
    pill_qty = await character.item_qty(uid, "筑基丹")

    assert statuses.count("big_success") == 1
    assert char.realm == 1
    assert char.stage == 0
    assert pill_qty == 0
