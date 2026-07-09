from __future__ import annotations

import random

import pytest
import pytest_asyncio

from config import events as EVENT_CFG
from config import realms as R
from models import db
from services import breakthrough, character


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "heart-tribulation.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _prepare_big(uid: int, source_realm: int):
    await character.create(uid, "问心客")
    stage = R.num_stages(source_realm) - 1
    cost = R.advance_cost(source_realm, stage)
    await character.set_progress(uid, source_realm, stage, cost)
    await db.execute("UPDATE characters SET root_bone=50 WHERE user_id=?", (uid,))
    await character.add_item(uid, R.BIG_BREAKTHROUGH[source_realm + 1]["pill"], 1)
    return cost


async def _remember_chat(uid: int, chat_id: int = -71601):
    await db.execute(
        "INSERT INTO bot_chat_members(chat_id, user_id, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen_at=?",
        (chat_id, uid, 1000, 1000))


@pytest.mark.asyncio
async def test_heart_reward_flag_migration_is_idempotent(tmp_path):
    path = str(tmp_path / "heart-migration.db")
    await db.init_db(path)
    await db.init_db(path)
    try:
        rows = await db.fetchall("PRAGMA table_info(tribulation_sessions)")
    finally:
        await db.close_db()

    assert "reward_flag" in {row["name"] for row in rows}


def test_heart_choice_exists_in_all_interactive_tribulations():
    """spec-v3 §7.1：金丹起天劫、神魂劫、虚空劫均有直面心魔选项。"""
    for actions in (
            EVENT_CFG.TRIBULATION_ACTIONS,
            EVENT_CFG.SHENHUN_TRIBULATION_ACTIONS,
            EVENT_CFG.XUKONG_TRIBULATION_ACTIONS):
        action = actions[EVENT_CFG.HEART_TRIBULATION_ACTION_KEY]
        assert action["label"] == "直面心魔"
        assert action["reward_flag"] == EVENT_CFG.HEART_TRIBULATION_REWARD_FLAG
        assert action["shield"] == 0
        assert action["heal_pct"] == 0.0
        assert action["ignore_guard"] is True


@pytest.mark.asyncio
async def test_heart_choice_takes_raw_damage_without_guard(temp_db, monkeypatch):
    uid = 71602
    await _prepare_big(uid, 1)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    start = await breakthrough.try_advance(uid, now=1000)
    row = await db.fetchone("SELECT * FROM tribulation_sessions WHERE user_id=?", (uid,))
    stats = R.base_stats(row["source_realm"], row["source_stage"])
    rng = random.Random(int(row["seed"]) + int(row["thunder_index"]) * 104729)
    raw = int((stats["hp"] * 0.18 + stats["df"] * 1.8) * (0.9 + rng.random() * 0.2))
    res = await breakthrough.choose_tribulation_action(
        uid, EVENT_CFG.HEART_TRIBULATION_ACTION_KEY, now=1001)
    updated = await db.fetchone("SELECT * FROM tribulation_sessions WHERE user_id=?", (uid,))

    assert start["status"] == "tribulation_choice"
    assert res["status"] == "tribulation_choice"
    assert updated["hp"] == stats["hp"] - raw
    assert updated["reward_flag"] == EVENT_CFG.HEART_TRIBULATION_REWARD_FLAG


@pytest.mark.asyncio
async def test_heart_success_grants_daoxin_buff_daohang_and_broadcast(temp_db, monkeypatch):
    uid = 71603
    await _prepare_big(uid, 1)
    await _remember_chat(uid)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    start = await breakthrough.try_advance(uid, now=1000)
    res = await breakthrough.choose_tribulation_action(
        uid, EVENT_CFG.HEART_TRIBULATION_ACTION_KEY, now=1001)
    res = await breakthrough.choose_tribulation_action(uid, "artifact", now=1002)
    res = await breakthrough.choose_tribulation_action(uid, "artifact", now=1003)
    char = await character.get_at(uid, now=1004)
    event = await db.fetchone(
        "SELECT amount FROM path_events WHERE user_id=? AND event_type='heart_tribulation'",
        (uid,))
    broadcast = await db.fetchone(
        "SELECT text FROM social_broadcasts WHERE user_id=? AND event_type='breakthrough.heart_success'",
        (uid,))

    buff = char.debuff_json["buffs"][EVENT_CFG.HEART_TRIBULATION_BUFF_KEY]
    assert start["status"] == "tribulation_choice"
    assert res["status"] == "big_success"
    assert res["heart_reward"] is True
    assert res["daohang"] == EVENT_CFG.HEART_TRIBULATION_DAOHANG
    assert char.realm == 2
    assert char.daohang == EVENT_CFG.HEART_TRIBULATION_DAOHANG
    assert event["amount"] == EVENT_CFG.HEART_TRIBULATION_DAOHANG
    assert buff["until"] == 1003 + EVENT_CFG.HEART_TRIBULATION_BUFF_DURATION
    assert buff["effects"] == {"seclusion_pct": EVENT_CFG.HEART_TRIBULATION_SECLUSION_PCT}
    assert "道心通明" in broadcast["text"]


@pytest.mark.asyncio
async def test_heart_failure_adds_extra_current_cultivation_loss_and_broadcast(temp_db, monkeypatch):
    uid = 71604
    cost = await _prepare_big(uid, 1)
    await _remember_chat(uid)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    start = await breakthrough.try_advance(uid, now=1000)
    await db.execute("UPDATE tribulation_sessions SET hp=1 WHERE user_id=?", (uid,))
    res = await breakthrough.choose_tribulation_action(
        uid, EVENT_CFG.HEART_TRIBULATION_ACTION_KEY, now=1001)
    row = await db.fetchone("SELECT realm, stage, cultivation FROM characters WHERE user_id=?", (uid,))
    broadcast = await db.fetchone(
        "SELECT text FROM social_broadcasts WHERE user_id=? AND event_type='breakthrough.heart_fail'",
        (uid,))

    expected_extra = int(cost * EVENT_CFG.HEART_TRIBULATION_FAIL_EXTRA_LOSS_PCT)
    expected_loss = int(cost * breakthrough.FAIL_CULT_LOSS) + expected_extra
    assert start["status"] == "tribulation_choice"
    assert res["status"] == "big_fail"
    assert res["heart_reward"] is True
    assert res["extra_loss"] == expected_extra
    assert res["loss"] == expected_loss
    assert row["realm"] == 1
    assert row["stage"] == R.num_stages(1) - 1
    assert row["cultivation"] == cost - expected_loss
    assert "心魔" in broadcast["text"]
