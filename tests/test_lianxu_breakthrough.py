from __future__ import annotations

import pytest
import pytest_asyncio

from config import realms as R
from handlers import cultivate
from models import db
from services import breakthrough, character


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "lianxu-breakthrough.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _prepare_lianxu(uid: int):
    await character.create(uid, "破虚客")
    await character.set_progress(uid, 4, 3, R.advance_cost(4, 3))
    await db.execute("UPDATE characters SET root_bone=50 WHERE user_id=?", (uid,))
    await character.add_item(uid, "炼虚丹", 1)


@pytest.mark.asyncio
async def test_lianxu_breakthrough_needs_pill_before_xukong(temp_db):
    uid = 9905
    await character.create(uid, "缺丹客")
    await character.set_progress(uid, 4, 3, R.advance_cost(4, 3))

    res = await breakthrough.try_advance(uid, now=1000)

    assert res == {"status": "need_pill", "pill": "炼虚丹"}


@pytest.mark.asyncio
async def test_lianxu_breakthrough_enters_xukong_choices(temp_db, monkeypatch):
    uid = 9906
    await _prepare_lianxu(uid)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    start = await breakthrough.try_advance(uid, now=1000)
    text = cultivate._bt_text(start)
    old_choice = await breakthrough.choose_tribulation_action(uid, "endure", now=1001)
    step = await breakthrough.choose_tribulation_action(uid, "source", now=1002)

    assert start["status"] == "tribulation_choice"
    assert [choice["key"] for choice in start["choices"]] == ["source", "artifact", "pill"]
    assert [choice["label"] for choice in start["choices"]] == ["凝守本源", "祭护体法宝", "服大还丹"]
    assert "虚空劫未尽" in text
    assert old_choice["status"] == "bad_action"
    assert step["status"] == "tribulation_choice"
    assert "虚空劫" in "".join(step["last_log"])
    assert "凝守本源" in "".join(step["last_log"])


@pytest.mark.asyncio
async def test_lianxu_xukong_failure_loses_cultivation_without_realm_drop(temp_db, monkeypatch):
    uid = 9907
    cost = R.advance_cost(4, 3)
    await _prepare_lianxu(uid)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    start = await breakthrough.try_advance(uid, now=1000)
    await db.execute("UPDATE tribulation_sessions SET hp=1 WHERE user_id=?", (uid,))
    res = await breakthrough.choose_tribulation_action(uid, "source", now=1001)
    row = await db.fetchone(
        "SELECT realm, stage, cultivation, big_fail_streak FROM characters WHERE user_id=?", (uid,))
    text = cultivate._bt_text(res)

    assert start["status"] == "tribulation_choice"
    assert res["status"] == "big_fail"
    assert res["loss"] == int(cost * breakthrough.FAIL_CULT_LOSS)
    assert row["realm"] == 4
    assert row["stage"] == 3
    assert row["cultivation"] == cost - res["loss"]
    assert row["big_fail_streak"] == 1
    assert "虚空劫凶险" in text
    assert "跌境" in text


@pytest.mark.asyncio
async def test_lianxu_big_fail_streak_increments_and_boosts_next_rate(temp_db, monkeypatch):
    uid = 9901
    await _prepare_lianxu(uid)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.99)

    first = await breakthrough.try_advance(uid, now=1000)
    await character.set_progress(uid, 4, 3, R.advance_cost(4, 3))
    await character.add_item(uid, "炼虚丹", 1)
    second = await breakthrough.try_advance(uid, now=2000)
    row = await db.fetchone("SELECT big_fail_streak FROM characters WHERE user_id=?", (uid,))

    assert first["status"] == "big_fail"
    assert first["rate"] == pytest.approx(0.45)
    assert first["guarantee_bonus"] == 0
    assert second["status"] == "big_fail"
    assert second["rate"] == pytest.approx(0.55)
    assert second["guarantee_bonus"] == pytest.approx(0.10)
    assert row["big_fail_streak"] == 2


@pytest.mark.asyncio
async def test_lianxu_success_clears_big_fail_streak_after_tribulation(temp_db, monkeypatch):
    uid = 9902
    await _prepare_lianxu(uid)
    await db.execute("UPDATE characters SET root_bone=100, big_fail_streak=2 WHERE user_id=?", (uid,))
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    start = await breakthrough.try_advance(uid, now=1000)
    res = start
    for idx in range(3):
        res = await breakthrough.choose_tribulation_action(uid, "artifact", now=1001 + idx)
    row = await db.fetchone(
        "SELECT realm, stage, big_fail_streak FROM characters WHERE user_id=?", (uid,))

    assert start["status"] == "tribulation_choice"
    assert start["guarantee_bonus"] == pytest.approx(0.20)
    assert res["status"] == "big_success"
    assert row["realm"] == 5
    assert row["stage"] == 0
    assert row["big_fail_streak"] == 0


@pytest.mark.asyncio
async def test_lianxu_guarantee_rate_is_capped_at_ninety_five_percent(temp_db, monkeypatch):
    uid = 9903
    await _prepare_lianxu(uid)
    await db.execute("UPDATE characters SET root_bone=100, big_fail_streak=9 WHERE user_id=?", (uid,))
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.99)

    res = await breakthrough.try_advance(uid, now=1000)

    assert res["status"] == "big_fail"
    assert res["guarantee_bonus"] == pytest.approx(0.90)
    assert res["rate"] == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_low_realm_big_breakthrough_ignores_lianxu_fail_streak(temp_db, monkeypatch):
    uid = 9904
    await character.create(uid, "筑基客")
    last_qi = R.num_stages(0) - 1
    await character.set_progress(uid, 0, last_qi, R.advance_cost(0, last_qi))
    await db.execute("UPDATE characters SET root_bone=50, big_fail_streak=7 WHERE user_id=?", (uid,))
    await character.add_item(uid, "筑基丹", 1)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.99)

    res = await breakthrough.try_advance(uid, now=1000)
    row = await db.fetchone("SELECT big_fail_streak FROM characters WHERE user_id=?", (uid,))

    assert res["status"] == "big_fail"
    assert res["rate"] == pytest.approx(breakthrough.big_success_rate(0, 50))
    assert res["guarantee_bonus"] == 0
    assert row["big_fail_streak"] == 7


def test_breakthrough_text_shows_lianxu_guarantee_bonus():
    text = cultivate._bt_text({
        "status": "tribulation_choice",
        "tribulation": True,
        "target_realm": 5,
        "thunder_index": 1,
        "total": 3,
        "hp": 52000,
        "rate": 0.65,
        "guarantee_bonus": 0.20,
        "choices": [],
        "tribulation_log": [],
    })

    assert "虚空劫未尽" in text
    assert "本次破境成功率：65%" in text
    assert "保底+20%" in text
