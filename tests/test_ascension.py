import sqlite3

import pytest
import pytest_asyncio

from config import ascension as CFG
from config import buffs as BUFFS
from config import realms as R
from models import db
from services import ascension, character


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "ascension.db"))
    try:
        yield
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_ascension_trial_requires_huashen_full_and_daohang(temp_db):
    uid = 9501
    await character.create(uid, "trial")
    await character.set_progress(uid, 4, 2, 0)

    assert (await ascension.trial(uid, now=1000))["status"] == "locked"
    await character.set_progress(uid, 4, 3, R.advance_cost(4, 3))
    assert (await ascension.trial(uid, now=1000))["status"] == "no_daohang"


@pytest.mark.asyncio
async def test_ascension_trial_grants_points_and_costs_daohang(temp_db):
    uid = 9502
    await character.create(uid, "trial-ok")
    await character.set_progress(uid, 4, 3, R.advance_cost(4, 3))
    await db.execute("UPDATE characters SET daohang=? WHERE user_id=?", (CFG.TRIAL_DAOHANG_COST + 100, uid))

    res = await ascension.trial(uid, now=1000)
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    state = await ascension.get(uid)

    assert res["status"] == "ok"
    assert row["daohang"] == 100
    assert state["points"] == CFG.TRIAL_POINT_REWARD


@pytest.mark.asyncio
async def test_ascension_trial_stays_unlocked_after_lianxu_breakthrough(temp_db):
    uid = 9510
    await character.create(uid, "trial-lianxu")
    await character.set_progress(uid, 5, 0, 0)
    await db.execute("UPDATE characters SET daohang=? WHERE user_id=?", (CFG.TRIAL_DAOHANG_COST + 100, uid))

    res = await ascension.trial(uid, now=1000)

    assert res["status"] == "ok"
    assert (await ascension.get(uid))["points"] == CFG.TRIAL_POINT_REWARD


@pytest.mark.asyncio
async def test_ascension_trial_weekly_cooldown(temp_db):
    """R-P1-2：每周仅一次飞升试炼——同周第二次拒绝，防囤道行无限刷飞升点。"""
    uid = 9509
    await character.create(uid, "weekly")
    await character.set_progress(uid, 4, 3, R.advance_cost(4, 3))
    await db.execute("UPDATE characters SET daohang=? WHERE user_id=?",
                     (CFG.TRIAL_DAOHANG_COST * 5, uid))

    first = await ascension.trial(uid, now=1000)
    second = await ascension.trial(uid, now=1500)  # 同一周

    assert first["status"] == "ok"
    assert second["status"] == "weekly_done"
    # 道行只被扣一次，飞升点只发一次。
    assert (await ascension.get(uid))["points"] == CFG.TRIAL_POINT_REWARD

    # 下一周（+8 天）恢复。
    third = await ascension.trial(uid, now=1000 + 8 * 86400)
    assert third["status"] == "ok"


@pytest.mark.asyncio
async def test_passive_upgrade_caps_at_five_levels(temp_db):
    uid = 9503
    await character.create(uid, "passive")
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 10, now=1000)

    for expected in range(1, CFG.PASSIVE_CAP + 1):
        res = await ascension.upgrade_passive(uid, "hp_pct", now=1000 + expected)
        assert res["status"] == "ok"
        assert res["level"] == expected

    assert (await ascension.upgrade_passive(uid, "hp_pct", now=2000))["status"] == "max"
    state = await ascension.get(uid)
    assert state["spent"]["hp_pct"] == CFG.PASSIVE_CAP


@pytest.mark.asyncio
async def test_passive_upgrade_title_uses_total_level(temp_db):
    uid = 9507
    await character.create(uid, "title")
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 3, now=1000)

    first = await ascension.upgrade_passive(uid, "hp_pct", now=1001)
    second = await ascension.upgrade_passive(uid, "atk_pct", now=1002)
    third = await ascension.upgrade_passive(uid, "df_pct", now=1003)
    state = await ascension.get(uid)

    assert first["title"] == "飞升新秀"
    assert second["title"] == "飞升新秀"
    assert third["title"] == "飞升真君"
    assert third["level"] == 1
    assert third["total_level"] == 3
    assert state["level"] == 3


@pytest.mark.asyncio
async def test_ascension_passive_enters_stat_clamp(temp_db):
    uid = 9504
    await character.create(uid, "clamp")
    await character.create_item_instance(uid, "聚灵佩", affixes={"hp_pct": 0.24})
    inst = (await character.item_instances(uid))[0]
    await character.equip_instance(uid, inst["id"])
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 10, now=1000)
    for _ in range(CFG.PASSIVE_CAP):
        await ascension.upgrade_passive(uid, "hp_pct", now=1000)

    st = await character.stats(await character.get(uid))
    raw = R.base_stats(0, 0)["hp"]

    assert st["hp"] == int(raw * (1 + BUFFS.SURVIVAL_PCT_CAP))


@pytest.mark.asyncio
async def test_ascension_seclusion_passive_improves_gain(temp_db):
    uid = 9505
    await character.create(uid, "seclusion")
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, CFG.PASSIVE_CAP, now=1000)
    for _ in range(CFG.PASSIVE_CAP):
        await ascension.upgrade_passive(uid, "seclusion_pct", now=1000)

    plain_uid = 9506
    await character.create(plain_uid, "plain")
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (plain_uid,))

    await character.start_seclusion(uid, now=1000)
    with_passive = await character.collect_seclusion(uid, now=4600)
    await character.start_seclusion(plain_uid, now=1000)
    without_passive = await character.collect_seclusion(plain_uid, now=4600)

    assert with_passive["gained"] > without_passive["gained"]


@pytest.mark.asyncio
async def test_overflow_condensation_keeps_remainder_and_records_event(temp_db):
    uid = 9511
    await character.create(uid, "overflow-remainder")

    async with db.transaction() as conn:
        first = await ascension.add_overflow_points_conn(
            conn, uid, CFG.OVERFLOW_CULTIVATION_PER_POINT - 1, now=1000)
    async with db.transaction() as conn:
        second = await ascension.add_overflow_points_conn(conn, uid, 1, now=1001)

    state = await ascension.get(uid, now=1001)
    event = await db.fetchone(
        "SELECT source, points_delta, balance_after FROM ascension_events "
        "WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (uid,))

    assert first["points"] == 0
    assert first["remainder"] == CFG.OVERFLOW_CULTIVATION_PER_POINT - 1
    assert second["points"] == 1
    assert second["remainder"] == 0
    assert state["points"] == 1
    assert state["overflow_week_points"] == 1
    assert event["source"] == "overflow"
    assert event["points_delta"] == 1
    assert event["balance_after"] == 1


@pytest.mark.asyncio
async def test_overflow_condensation_weekly_cap_discards_full_excess(temp_db):
    uid = 9512
    await character.create(uid, "overflow-cap")
    unit = CFG.OVERFLOW_CULTIVATION_PER_POINT

    async with db.transaction() as conn:
        capped = await ascension.add_overflow_points_conn(
            conn, uid, unit * 20 + 12_345, now=1000)
    async with db.transaction() as conn:
        blocked = await ascension.add_overflow_points_conn(
            conn, uid, unit * 5 + 50_000, now=1001)
    async with db.transaction() as conn:
        next_week = await ascension.add_overflow_points_conn(
            conn, uid, unit - 12_345, now=1000 + 8 * 86400)

    state = await ascension.get(uid, now=1000 + 8 * 86400)
    assert capped["points"] == CFG.OVERFLOW_WEEKLY_CAP
    assert capped["remainder"] == 12_345
    assert blocked["points"] == 0
    assert blocked["remainder"] == 12_345
    assert next_week["points"] == 1
    assert next_week["remainder"] == 0
    assert state["points"] == CFG.OVERFLOW_WEEKLY_CAP + 1
    assert state["overflow_week_points"] == 1


async def _max_ascension_passives(uid: int, now: int):
    async with db.transaction() as conn:
        await ascension.add_points_conn(
            conn, uid, CFG.PASSIVE_CAP * len(CFG.PASSIVES), now=now,
            source="test_setup")
    for key in CFG.PASSIVES:
        for offset in range(CFG.PASSIVE_CAP):
            res = await ascension.upgrade_passive(uid, key, now=now + offset + 1)
            assert res["status"] == "ok"


@pytest.mark.asyncio
async def test_tianmen_requires_all_passives_maxed(temp_db):
    uid = 9513
    await character.create(uid, "tianmen-locked")
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 100, now=1000, source="test_setup")

    res = await ascension.contribute_tianmen(uid, None, now=1001)

    assert res["status"] == "passives_not_max"
    assert (await ascension.get(uid))["points"] == 100


@pytest.mark.asyncio
async def test_tianmen_all_in_crosses_levels_and_grants_milestones(temp_db):
    uid = 9514
    await character.create(uid, "tianmen-all")
    await _max_ascension_passives(uid, now=1000)
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 51_316, now=1100, source="test_setup")

    res = await ascension.contribute_tianmen(uid, None, now=1200)
    state = await ascension.get(uid, now=1200)
    rewards = await db.fetchall(
        "SELECT item_key, bound, qty FROM inventory WHERE user_id=? ORDER BY item_key",
        (uid,))
    event = await db.fetchone(
        "SELECT source, points_delta, balance_after FROM ascension_events "
        "WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (uid,))

    assert res["status"] == "tianmen_ok"
    assert res["level"] == 9
    assert res["progress"] == 216
    assert res["points"] == 0
    assert state["tianmen_level"] == 9
    assert state["tianmen_progress"] == 216
    assert state["tianmen_title"] == "太虚留名"
    assert [(row["item_key"], row["bound"], row["qty"]) for row in rewards] == [
        ("保命符", 1, 1),
        ("天外残玉", 1, 1),
        ("转修令", 1, 1),
    ]
    assert event["source"] == "tianmen"
    assert event["points_delta"] == -51_316
    assert event["balance_after"] == 0


@pytest.mark.asyncio
async def test_tianmen_partial_contribution_keeps_progress(temp_db):
    uid = 9515
    await character.create(uid, "tianmen-partial")
    await _max_ascension_passives(uid, now=1000)
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 1_000, now=1100, source="test_setup")

    first = await ascension.contribute_tianmen(uid, 100, now=1200)
    second = await ascension.contribute_tianmen(uid, 100, now=1201)

    assert first["level"] == 1
    assert first["progress"] == 0
    assert second["level"] == 1
    assert second["progress"] == 100
    assert second["points"] == 800


@pytest.mark.asyncio
async def test_ascension_schema_migrates_existing_balance_without_changes(tmp_path):
    path = tmp_path / "legacy-ascension.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE ascension (user_id INTEGER PRIMARY KEY, level INTEGER NOT NULL DEFAULT 0, "
        "points INTEGER NOT NULL DEFAULT 0, spent_json TEXT NOT NULL DEFAULT '{}', "
        "updated_at INTEGER NOT NULL, last_trial_week TEXT)")
    conn.execute(
        "INSERT INTO ascension(user_id, level, points, spent_json, updated_at) "
        "VALUES(1,20,199944,?,1000)",
        ('{"hp_pct":5,"atk_pct":5,"df_pct":5,"seclusion_pct":5}',))
    conn.commit()
    conn.close()

    await db.init_db(str(path))
    try:
        state = await ascension.get(1, now=1000)
        events = await db.fetchall("SELECT * FROM ascension_events WHERE user_id=1")
        assert state["points"] == 199_944
        assert state["tianmen_level"] == 0
        assert state["tianmen_progress"] == 0
        assert state["overflow_remainder"] == 0
        assert state["overflow_week_points"] == 0
        assert events == []
    finally:
        await db.close_db()
