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
