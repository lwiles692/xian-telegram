from __future__ import annotations

import pytest
import pytest_asyncio

from handlers import daily as daily_handler
from handlers import sect as sect_handler
from models import db
from services import character, daily, game_events, quests, sect


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "daily-stamina.db"))
    yield
    await db.close_db()


@pytest.mark.asyncio
async def test_all_daily_rewards_stack_above_cap_once(temp_db, monkeypatch):
    uid = 9101
    now = 1_000
    await character.create(uid, "勤修道友")
    await character.set_progress(uid, 1, 0, 0)
    await character.add_stone(uid, 500)
    assert (await sect.create(uid, "勤修宗", now=now))["status"] == "ok"
    await db.execute(
        "UPDATE characters SET stamina=120, stamina_at=? WHERE user_id=?",
        (now, uid),
    )

    checked = await daily.checkin(uid, now=now)
    async with db.transaction() as conn:
        for _ in range(3):
            await game_events.emit_conn(conn, uid, "explore.win", {"amount": 1}, now=now)
        await game_events.emit_conn(conn, uid, "craft.done", {"amount": 1}, now=now)
        await game_events.emit_conn(conn, uid, "pvp.win", {"amount": 1}, now=now)
    explore_reward = await quests.claim(uid, "daily_explore", now=now)
    craft_reward = await quests.claim(uid, "daily_craft", now=now)
    pvp_reward = await quests.claim(uid, "daily_pvp_win", now=now)
    sect_reward = await sect.task(uid, now=now)
    row = await db.fetchone("SELECT stamina FROM characters WHERE user_id=?", (uid,))

    assert checked["stamina"] == 10
    assert explore_reward["reward"]["stamina"] == 30
    assert craft_reward["reward"]["stamina"] == 10
    assert pvp_reward["reward"]["stamina"] == 10
    assert sect_reward["stamina"] == 20
    assert row["stamina"] == 200
    assert "精力 +10" in daily_handler._ok_text(checked)
    assert "精力 +30" in quests.reward_text(explore_reward["reward"])
    assert "精力 +20" in sect_handler._result_text(sect_reward)

    assert (await daily.checkin(uid, now=now + 1))["status"] == "done"
    assert (await quests.claim(uid, "daily_explore", now=now + 1))["status"] == "claimed"
    assert (await sect.task(uid, now=now + 1))["status"] == "done"
    row = await db.fetchone("SELECT stamina FROM characters WHERE user_id=?", (uid,))
    assert row["stamina"] == 200

    next_day = await daily.checkin(uid, now=now + 24 * 3600)
    row = await db.fetchone("SELECT stamina FROM characters WHERE user_id=?", (uid,))
    assert next_day["status"] == "ok"
    assert row["stamina"] == 210

    monkeypatch.setattr(character.time, "time", lambda: now + 24 * 3600 + 2)
    spent = await character.reserve_stamina_for_action(uid, 100)
    recovered = await character.get_at(uid, now=now + 24 * 3600 + 2 + 204)

    assert spent["status"] == "ok"
    assert spent["stamina_left"] == 110
    assert recovered.stamina == 111
