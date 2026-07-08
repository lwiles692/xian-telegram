import pytest
import pytest_asyncio

from config import realms as R
from models import db
from services import ascension, character, settle


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


def test_overflow_split_full_lianxu_gives_daohang_and_ascension_points():
    cost = R.advance_cost(5, 3)
    kept, daohang, asc_pts = settle.overflow_split(5, 3, cost, 1000)

    assert kept == cost
    assert daohang == int(1000 * settle.DAOHANG_FULL_REALM_RATE)  # 80 @ 0.08
    assert asc_pts == 200  # 飞升点转化率不变（下游有硬上限）


def test_overflow_split_huashen_cap_transition_gives_daohang_only():
    cost = R.advance_cost(4, 3)
    kept, daohang, asc_pts = settle.overflow_split(4, 3, cost, 1000)

    assert kept == cost
    assert daohang == int(1000 * settle.DAOHANG_PRE_CAP_RATE)  # 30 @ 0.03
    assert asc_pts == 0


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
    res = await character.collect_seclusion(uid, now=1000 + 3600)
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
    assert asc["points"] > 0
    assert event["amount"] == res["daohang"]


@pytest.mark.asyncio
async def test_collect_seclusion_converts_huashen_transition_without_ascension(temp_db):
    uid = 9405
    cost = R.advance_cost(4, 3)
    await character.create(uid, "precap")
    await character.set_progress(uid, 4, 3, cost)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))

    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=1000 + 3600)
    row = await db.fetchone("SELECT cultivation, daohang FROM characters WHERE user_id=?", (uid,))
    asc = await ascension.get(uid)

    assert res["status"] == "collected"
    assert res["cultivation"] == cost
    assert res["daohang"] > 0
    assert res.get("ascension", 0) == 0
    assert row["cultivation"] == cost
    assert row["daohang"] == res["daohang"]
    assert asc["points"] == 0


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
    assert asc["points"] > 0


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
