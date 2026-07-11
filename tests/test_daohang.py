from __future__ import annotations

import time

import pytest
import pytest_asyncio

from config import realms as R
from models import db
from services import ascension, character, settle


async def _set_overflow_grace_until(ts: int):
    await db.execute(
        "UPDATE game_flags SET value=? WHERE key=?",
        (str(int(ts)), db.GAME_FLAG_OVERFLOW_DEMOTE_GRACE_UNTIL))
    character.clear_game_flag_cache()


def _assert_overflow_notice(text: str, grace_until: int):
    assert "宽限截止日期" in text
    assert time.strftime("%Y-%m-%d", time.localtime(grace_until)) in text
    assert "降档后档位" in text
    assert "3% 道行 / 0 飞升点" in text
    assert "突破炼虚" in text
    assert "恢复完整分流" in text


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "daohang.db"))
    try:
        yield
    finally:
        await db.close_db()


def test_overflow_to_daohang_full_lianxu():
    cost = R.advance_cost(5, 3)
    kept, daohang = settle.overflow_to_daohang(5, 3, cost, 1000)

    assert kept == cost
    assert daohang == int(1000 * settle.DAOHANG_FULL_REALM_RATE)  # 80 @ 0.08


def test_overflow_split_full_lianxu_returns_condensable_overflow():
    cost = R.advance_cost(5, 3)
    kept, daohang, asc_overflow = settle.overflow_split(5, 3, cost, 1000)

    assert kept == cost
    assert daohang == int(1000 * settle.DAOHANG_FULL_REALM_RATE)  # 80 @ 0.08
    assert asc_overflow == 1000


def test_overflow_split_huashen_cap_transition_gives_daohang_only():
    cost = R.advance_cost(4, 3)
    kept, daohang, asc_overflow = settle.overflow_split(
        4, 3, cost, 1000, now=200, grace_until=100)

    assert kept == cost
    assert daohang == int(1000 * settle.DAOHANG_PRE_CAP_RATE)  # 30 @ 0.03
    assert asc_overflow == 0


def test_overflow_split_huashen_grace_uses_full_split():
    cost = R.advance_cost(4, 3)
    kept, daohang, asc_overflow = settle.overflow_split(
        4, 3, cost, 1000, now=100, grace_until=200)

    assert kept == cost
    assert daohang == int(1000 * settle.DAOHANG_FULL_REALM_RATE)
    assert asc_overflow == 1000


def test_overflow_to_daohang_other_progress_is_unchanged():
    kept, daohang = settle.overflow_to_daohang(3, 2, 100, 1000)

    assert kept == 1100
    assert daohang == 0


@pytest.mark.asyncio
async def test_collect_seclusion_converts_lianxu_cap_overflow(temp_db):
    uid = 9401
    cost = R.advance_cost(5, 3)
    await character.create(uid, "cap")
    await character.set_progress(uid, 5, 3, cost)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))

    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=1000 + 12 * 3600)
    row = await db.fetchone("SELECT cultivation, daohang FROM characters WHERE user_id=?", (uid,))
    asc = await ascension.get(uid)
    event = await db.fetchone(
        "SELECT event_type, amount FROM path_events WHERE user_id=? AND event_type='overflow'",
        (uid,))

    assert res["status"] == "collected"
    assert res["cultivation"] == cost
    assert res["daohang"] > 0
    assert row["cultivation"] == cost
    assert row["daohang"] == res["daohang"]
    assert asc["points"] == res["ascension"]
    assert asc["points"] == 1
    assert asc["overflow_remainder"] > 0
    assert event["amount"] == res["daohang"]


@pytest.mark.asyncio
async def test_collect_seclusion_converts_huashen_transition_without_ascension(temp_db):
    uid = 9405
    cost = R.advance_cost(4, 3)
    await character.create(uid, "precap")
    await character.set_progress(uid, 4, 3, cost)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    await _set_overflow_grace_until(999)

    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=1000 + 1800)
    row = await db.fetchone("SELECT cultivation, daohang FROM characters WHERE user_id=?", (uid,))
    asc = await ascension.get(uid)
    gained = settle.seclusion_gain(4, 3, 1000, 1000 + 1800, root_bone=0)

    assert res["status"] == "collected"
    assert res["cultivation"] == cost
    assert res["daohang"] == int(gained * settle.DAOHANG_PRE_CAP_RATE)
    assert res.get("ascension", 0) == 0
    assert res["overflow"]["status"] == "pre_cap"
    assert row["cultivation"] == cost
    assert row["daohang"] == res["daohang"]
    assert asc["points"] == 0


@pytest.mark.asyncio
async def test_collect_seclusion_huashen_grace_accumulates_condensation_progress(temp_db):
    uid = 9406
    cost = R.advance_cost(4, 3)
    grace_until = int(time.time()) + 3600
    await character.create(uid, "grace")
    await character.set_progress(uid, 4, 3, cost)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    await _set_overflow_grace_until(grace_until)

    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=1000 + 1800)
    row = await db.fetchone("SELECT cultivation, daohang FROM characters WHERE user_id=?", (uid,))
    asc = await ascension.get(uid)
    gained = settle.seclusion_gain(4, 3, 1000, 1000 + 1800, root_bone=0)

    assert res["status"] == "collected"
    assert res["cultivation"] == cost
    assert res["daohang"] == int(gained * settle.DAOHANG_FULL_REALM_RATE)
    assert res["ascension"] == 0
    assert res["overflow"]["status"] == "grace_full"
    assert row["daohang"] == res["daohang"]
    assert asc["points"] == 0
    assert asc["overflow_remainder"] == gained

    from handlers import me as me_handler
    text, _ = await me_handler.render_me(uid)
    assert res["overflow"]["label"] in text


@pytest.mark.asyncio
async def test_touch_activity_auto_collect_converts_overflow(temp_db):
    uid = 9402
    cost = R.advance_cost(5, 3)
    await character.create(uid, "auto")
    await character.set_progress(uid, 5, 3, cost)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    await db.execute("UPDATE users SET last_seen_at=? WHERE tg_user_id=?", (1000, uid))

    res = await character.touch_activity(uid, "auto", now=1000 + 7200)
    row = await db.fetchone("SELECT cultivation, daohang FROM characters WHERE user_id=?", (uid,))
    asc = await ascension.get(uid)

    assert res["status"] == "ok"
    assert res["auto_cultivation"] > 0
    assert row["cultivation"] == cost
    assert row["daohang"] > 0
    assert asc["points"] == 0
    assert asc["overflow_remainder"] > 0


@pytest.mark.asyncio
async def test_overflow_daohang_weekly_cap(temp_db):
    uid = 9403
    cost = R.advance_cost(5, 3)
    await character.create(uid, "capd")
    await character.set_progress(uid, 5, 3, cost)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))

    # 一次满离线收功，溢出道行远超周上限 → 封顶
    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=1000 + 12 * 3600)
    assert res["daohang"] == settle.OVERFLOW_DAOHANG_WEEKLY_CAP

    # 同周再次收功不再入账道行（额度已用尽）
    await character.start_seclusion(uid, now=1000 + 12 * 3600)
    res2 = await character.collect_seclusion(uid, now=1000 + 24 * 3600)
    assert res2["daohang"] == 0
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    assert row["daohang"] == settle.OVERFLOW_DAOHANG_WEEKLY_CAP


@pytest.mark.asyncio
async def test_overflow_daohang_weekly_cap_shared_across_grace_and_lianxu(temp_db):
    uid = 9407
    huashen_cost = R.advance_cost(4, 3)
    lianxu_cost = R.advance_cost(5, 3)
    await character.create(uid, "shared")
    await character.set_progress(uid, 4, 3, huashen_cost)
    await db.execute("UPDATE characters SET root_bone=100 WHERE user_id=?", (uid,))
    await _set_overflow_grace_until(int(time.time()) + 3600)

    await character.start_seclusion(uid, now=1000)
    first = await character.collect_seclusion(uid, now=1000 + 12 * 3600)
    assert first["daohang"] == settle.OVERFLOW_DAOHANG_WEEKLY_CAP
    assert first["ascension"] == 1

    await character.set_progress(uid, 5, 3, lianxu_cost)
    await character.start_seclusion(uid, now=1000 + 12 * 3600 + 1)
    second = await character.collect_seclusion(uid, now=1000 + 24 * 3600)
    row = await db.fetchone(
        "SELECT daohang FROM characters WHERE user_id=?", (uid,))

    assert second["daohang"] == 0
    assert second["ascension"] >= 1
    assert row["daohang"] == settle.OVERFLOW_DAOHANG_WEEKLY_CAP


@pytest.mark.asyncio
async def test_game_flags_init_is_idempotent(tmp_path):
    path = tmp_path / "flags.db"
    await db.init_db(str(path))
    row = await db.fetchone(
        "SELECT value FROM game_flags WHERE key=?",
        (db.GAME_FLAG_OVERFLOW_DEMOTE_GRACE_UNTIL,))
    assert int(row["value"]) > int(time.time())
    await db.execute(
        "UPDATE game_flags SET value=? WHERE key=?",
        ("12345", db.GAME_FLAG_OVERFLOW_DEMOTE_GRACE_UNTIL))
    await db.close_db()

    await db.init_db(str(path))
    again = await db.fetchone(
        "SELECT value FROM game_flags WHERE key=?",
        (db.GAME_FLAG_OVERFLOW_DEMOTE_GRACE_UNTIL,))
    assert again["value"] == "12345"
    await db.close_db()


@pytest.mark.asyncio
async def test_overflow_notice_three_surfaces_include_deadline_and_recovery(temp_db):
    from handlers import cultivate as cultivate_handler
    from handlers import help as help_handler

    uid = 9408
    cost = R.advance_cost(4, 3)
    grace_until = 2_000_000_000
    await character.create(uid, "notice")
    await character.set_progress(uid, 4, 3, cost)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    await _set_overflow_grace_until(grace_until)

    version_notice = await help_handler.render_version_notice()
    help_text = await help_handler.render_help()
    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=1000 + 1800)
    collect_text = cultivate_handler._collect_text(res)

    assert "三期·炼虚开放公告" in version_notice
    assert "炼虚溢出分流" in help_text
    for text in (version_notice, help_text, collect_text):
        _assert_overflow_notice(text, grace_until)


@pytest.mark.asyncio
async def test_refine_sink_consumes_daohang_within_clamp(temp_db):
    from config import dao_paths as DCFG
    from services import dao_path

    uid = 9404
    await character.create(uid, "refiner")
    await character.set_progress(uid, 3, 0, 0)  # 元婴，够解锁道途
    await db.execute("UPDATE characters SET daohang=100000 WHERE user_id=?", (uid,))
    await dao_path.unlock(uid, "sword")

    before = await dao_path.active_bonuses(uid)
    stat = DCFG.REFINE_STATS["sword"]  # crit_pct（剑修未触顶维度）
    res = await dao_path.refine(uid, "sword")
    assert res["status"] == "refine_ok"
    assert res["level"] == 1
    assert res["cost"] == DCFG.refine_cost(0)
    after = await dao_path.active_bonuses(uid)
    # 只强化淬炼维度，主攻伐维度不变
    assert after[stat] == round(before[stat] + DCFG.REFINE_PER_LEVEL_PCT, 4)
    assert after["atk_pct"] == before["atk_pct"]
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    assert row["daohang"] == 100000 - DCFG.refine_cost(0)

    # 淬炼封顶后不再消耗道行
    for _ in range(DCFG.REFINE_MAX_LEVEL):
        await dao_path.refine(uid, "sword")
    maxed = await dao_path.refine(uid, "sword")
    assert maxed["status"] == "refine_max"
    assert maxed["level"] == DCFG.REFINE_MAX_LEVEL
