import pytest
import pytest_asyncio

from config import dao_paths as CFG
from config import buffs as BUFFS
from handlers import dao_path as dao_path_handler
from models import db
from services import ascension, character, dao_path


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "dao-path.db"))
    try:
        yield
    finally:
        await db.close_db()


def test_dao_path_config_covers_five_paths_with_entry_scale():
    assert set(CFG.DAO_PATHS) == {"sword", "body", "alchemy", "forge", "talisman"}
    for path in CFG.DAO_PATHS.values():
        first = path["bonuses"][0]
        assert any(0.02 <= v <= 0.03 for k, v in first.items() if k.endswith("_pct"))


def test_dao_path_bonus_text_uses_chinese_labels():
    # 入参乱序，输出按 STAT_LABEL 固定顺序（速度加成先于闭关加成）。
    text = dao_path_handler._bonus_text({"seclusion_pct": 0.11, "spd_pct": 0.06})

    assert text == "速度加成+6%、闭关加成+11%"
    assert "seclusion_pct" not in text
    assert "spd_pct" not in text


@pytest.mark.asyncio
async def test_yuanying_can_unlock_first_path_for_free(temp_db):
    uid = 9301
    await character.create(uid, "dao")
    await character.set_progress(uid, 3, 0, 0)

    res = await dao_path.unlock(uid, "sword", now=1000)
    active = await dao_path.active_path(uid)
    events = await db.fetchall("SELECT event_type, path_key FROM path_events WHERE user_id=?", (uid,))

    assert res["status"] == "unlocked"
    assert active["path_key"] == "sword"
    assert active["rank"] == 0
    assert events[0]["event_type"] == "unlock" and events[0]["path_key"] == "sword"


@pytest.mark.asyncio
async def test_lower_realm_cannot_unlock_path(temp_db):
    uid = 9302
    await character.create(uid, "low")
    await character.set_progress(uid, 2, 3, 0)

    assert (await dao_path.unlock(uid, "body", now=1000))["status"] == "locked"
    assert await dao_path.list_paths(uid) == []


@pytest.mark.asyncio
async def test_second_path_requires_switch_flow_placeholder(temp_db):
    uid = 9303
    await character.create(uid, "switch")
    await character.set_progress(uid, 3, 0, 0)

    assert (await dao_path.unlock(uid, "sword", now=1000))["status"] == "unlocked"
    res = await dao_path.unlock(uid, "body", now=1001)

    assert res["status"] == "need_switch"
    assert [row["path_key"] for row in await dao_path.list_paths(uid)] == ["sword"]


@pytest.mark.asyncio
async def test_path_menu_switches_to_new_path_after_first_choice(temp_db):
    from handlers import dao_path as path_handler

    uid = 9312
    await character.create(uid, "path-ui")
    await character.set_progress(uid, 3, 0, 0)

    _text, first_markup = await path_handler.render_path(uid)
    first_buttons = [
        (button.text, button.callback_data)
        for row in first_markup.inline_keyboard
        for button in row
    ]

    assert any(text == "选择 体修" and data.startswith("path:unlock:body:")
               for text, data in first_buttons)

    await dao_path.unlock(uid, "sword", now=1000)
    _text, switch_markup = await path_handler.render_path(uid)
    switch_buttons = [
        (button.text, button.callback_data)
        for row in switch_markup.inline_keyboard
        for button in row
    ]

    assert any(text == "转修 体修" and data.startswith("path:switch:body:")
               for text, data in switch_buttons)
    assert not any(text == "选择 体修" for text, _data in switch_buttons)


@pytest.mark.asyncio
async def test_active_path_bonuses_feed_stats_and_clamp(temp_db):
    uid = 9304
    await character.create(uid, "bonus")
    await character.set_progress(uid, 3, 0, 0)
    await dao_path.unlock(uid, "sword", now=1000)
    base = await character.stats(await character.get(uid))
    await db.execute("UPDATE dao_paths SET rank=4 WHERE user_id=? AND path_key='sword'", (uid,))

    buffed = await character.stats(await character.get(uid))
    raw_atk = base["atk"]

    assert buffed["atk"] > base["atk"]
    assert buffed["atk"] <= int(raw_atk * (1 + BUFFS.ATTACK_PCT_CAP))


@pytest.mark.asyncio
async def test_talisman_path_improves_seclusion_gain(temp_db):
    uid = 9305
    await character.create(uid, "talisman")
    await character.set_progress(uid, 3, 0, 0)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    await dao_path.unlock(uid, "talisman", now=1000)

    no_path_uid = 9306
    await character.create(no_path_uid, "plain")
    await character.set_progress(no_path_uid, 3, 0, 0)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (no_path_uid,))

    await character.start_seclusion(uid, now=1000)
    with_path = await character.collect_seclusion(uid, now=4600)
    await character.start_seclusion(no_path_uid, now=1000)
    without_path = await character.collect_seclusion(no_path_uid, now=4600)

    assert with_path["gained"] > without_path["gained"]


@pytest.mark.asyncio
async def test_rank_up_costs_daohang_materials_and_emits_event(temp_db):
    uid = 9307
    await character.create(uid, "ranker")
    await character.set_progress(uid, 3, 0, 0)
    await dao_path.unlock(uid, "sword", now=1000)
    await db.execute("UPDATE characters SET daohang=? WHERE user_id=?", (500, uid))

    res = await dao_path.rank_up(uid, "sword", now=1100)
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    path = await dao_path.active_path(uid)
    event = await db.fetchone(
        "SELECT event_type, amount FROM path_events WHERE user_id=? AND event_type='rank_up'",
        (uid,))

    assert res["status"] == "ok"
    assert path["rank"] == 1
    assert row["daohang"] == 400
    assert event["amount"] == 1


@pytest.mark.asyncio
async def test_rank_up_requires_material_for_higher_rank(temp_db):
    uid = 9308
    await character.create(uid, "material")
    await character.set_progress(uid, 3, 0, 0)
    await dao_path.unlock(uid, "sword", now=1000)
    await db.execute("UPDATE dao_paths SET rank=1 WHERE user_id=? AND path_key='sword'", (uid,))
    await db.execute("UPDATE characters SET daohang=? WHERE user_id=?", (1000, uid))

    assert (await dao_path.rank_up(uid, "sword", now=1100))["status"] == "no_material"
    await character.add_item(uid, "星陨砂", 1, bound=1)
    res = await dao_path.rank_up(uid, "sword", now=1200)

    assert res["status"] == "ok"
    assert (await dao_path.active_path(uid))["rank"] == 2
    assert await character.item_qty(uid, "星陨砂") == 0


@pytest.mark.asyncio
async def test_master_rank_consumes_ascension_point_after_material_check(temp_db):
    uid = 9311
    await character.create(uid, "master")
    await character.set_progress(uid, 4, 3, 0)
    await dao_path.unlock(uid, "sword", now=1000)
    await db.execute("UPDATE dao_paths SET rank=3 WHERE user_id=? AND path_key='sword'", (uid,))
    await db.execute("UPDATE characters SET daohang=? WHERE user_id=?", (2000, uid))
    await character.add_item(uid, "天外残玉", 1, bound=1)

    short = await dao_path.rank_up(uid, "sword", now=1100)
    before = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))

    assert short["status"] == "no_ascension_points"
    assert before["daohang"] == 2000
    assert await character.item_qty(uid, "天外残玉") == 1

    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 1, now=1110)
    res = await dao_path.rank_up(uid, "sword", now=1200)
    after = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))
    state = await ascension.get(uid)

    assert res["status"] == "ok"
    assert (await dao_path.active_path(uid))["rank"] == 4
    assert after["daohang"] == 400
    assert state["points"] == 0
    assert await character.item_qty(uid, "天外残玉") == 0


@pytest.mark.asyncio
async def test_switch_path_consumes_bound_token_keeps_history_and_cools_down(temp_db):
    uid = 9309
    await character.create(uid, "switcher")
    await character.set_progress(uid, 3, 0, 0)
    await character.add_stone(uid, CFG.SWITCH_STONE_COST * 2)
    await dao_path.unlock(uid, "sword", now=1000)
    await db.execute("UPDATE dao_paths SET rank=2 WHERE user_id=? AND path_key='sword'", (uid,))
    await character.add_item(uid, CFG.SWITCH_TOKEN, 1, bound=0)

    assert (await dao_path.switch(uid, "body", now=2000))["status"] == "no_token"
    await character.add_item(uid, CFG.SWITCH_TOKEN, 2, bound=1)
    res = await dao_path.switch(uid, "body", now=2000)
    active = await dao_path.active_path(uid)
    paths = {row["path_key"]: row for row in await dao_path.list_paths(uid)}
    cooldown = await dao_path.switch(uid, "sword", now=2001)

    assert res["status"] == "ok"
    assert active["path_key"] == "body"
    assert paths["sword"]["rank"] == 2
    assert paths["body"]["rank"] == 0
    assert await character.item_qty(uid, CFG.SWITCH_TOKEN, bound=0) == 1
    assert await character.item_qty(uid, CFG.SWITCH_TOKEN, bound=1) == 1
    assert cooldown["status"] == "cooldown"


@pytest.mark.asyncio
async def test_switch_after_cooldown_reactivates_old_path_without_rank_loss(temp_db):
    uid = 9310
    await character.create(uid, "back")
    await character.set_progress(uid, 3, 0, 0)
    await character.add_stone(uid, CFG.SWITCH_STONE_COST * 3)
    await dao_path.unlock(uid, "sword", now=1000)
    await db.execute("UPDATE dao_paths SET rank=3 WHERE user_id=? AND path_key='sword'", (uid,))
    await character.add_item(uid, CFG.SWITCH_TOKEN, 2, bound=1)
    await dao_path.switch(uid, "body", now=2000)

    res = await dao_path.switch(uid, "sword", now=2000 + CFG.SWITCH_COOLDOWN_SECONDS)
    active = await dao_path.active_path(uid)

    assert res["status"] == "ok"
    assert active["path_key"] == "sword"
    assert active["rank"] == 3
