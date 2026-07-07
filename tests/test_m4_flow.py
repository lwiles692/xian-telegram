import pytest
import pytest_asyncio

from config import buffs as BUFFS
from config import weekly_events as W
from models import db
from services import character, pvp, season, sect, sect_war, settle, weekly_events

# 落在据点战开放窗口内（周六 20:30，上海时区）的确定性时间戳。
WAR_OPEN = 1641040200


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "m4.db"))
    try:
        yield
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_weekly_activity_gives_bound_material_and_caps_daohang(temp_db):
    uid = 9601
    await character.create(uid, "event")
    await character.set_progress(uid, 4, 0, 0)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (W.RUN_STAMINA_COST * 4, 1000, uid))

    gains = []
    for idx in range(4):
        res = await weekly_events.run(uid, "tianmo", now=1000 + idx)
        assert res["status"] == "ok"
        assert res["bound"] == 1
        gains.append(res["daohang"])
    row = await db.fetchone("SELECT daohang FROM weekly_activity WHERE user_id=?", (uid,))

    assert sum(gains) == W.WEEKLY_DAOHANG_CAP
    assert row["daohang"] == W.WEEKLY_DAOHANG_CAP
    assert await character.item_qty(uid, W.ACTIVITY_MATERIAL, bound=1) == 4
    assert await character.item_qty(uid, W.ACTIVITY_MATERIAL, bound=0) == 0


@pytest.mark.asyncio
async def test_weekly_activity_records_activity_window(temp_db):
    uid = 9602
    await character.create(uid, "window")
    await db.execute("UPDATE characters SET stamina=? WHERE user_id=?", (100, uid))

    open_key = weekly_events.current_theme_key(2000)
    await weekly_events.run(uid, open_key, now=2000)
    row = await db.fetchone(
        "SELECT kind, source_key FROM activity_windows WHERE user_id=?",
        (uid,))

    assert row["kind"] == "weekly_activity"
    assert row["source_key"] == open_key


@pytest.mark.asyncio
async def test_weekly_activity_settles_stamina_regen_before_cost(temp_db):
    uid = 9615
    await character.create(uid, "regen")
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (0, 1000, uid))
    now = 1000 + W.RUN_STAMINA_COST * settle.STAMINA_REGEN_SECONDS
    open_key = weekly_events.current_theme_key(now)

    res = await weekly_events.run(uid, open_key, now=now)
    row = await db.fetchone(
        "SELECT stamina, stamina_at, daohang FROM characters WHERE user_id=?",
        (uid,))

    assert res["status"] == "ok"
    assert row["stamina"] == 0
    assert row["stamina_at"] == now
    assert row["daohang"] == res["daohang"]


@pytest.mark.asyncio
async def test_weekly_theme_rotates_and_rejects_closed(temp_db):
    uid = 9607
    await character.create(uid, "rotate")
    await db.execute("UPDATE characters SET stamina=? WHERE user_id=?", (500, uid))

    # 不同周轮换出不同主题。
    keys = {weekly_events.current_theme_key(wk * 7 * 86400 + 1000) for wk in range(3)}
    assert len(keys) == len(W.WEEKLY_THEMES)

    open_key = weekly_events.current_theme_key(1000)
    closed_key = next(k for k in W.WEEKLY_THEMES if k != open_key)
    ok = await weekly_events.run(uid, open_key, now=1000)
    closed = await weekly_events.run(uid, closed_key, now=1000)

    assert ok["status"] == "ok"
    assert closed["status"] == "closed"
    assert closed["open"] == open_key


@pytest.mark.asyncio
async def test_sect_outpost_capture_adds_buff_under_clamp(temp_db):
    uid = 9603
    await character.create(uid, "leader")
    await character.set_progress(uid, 4, 0, 0)  # 化神圆满方能击败据点守卫
    await character.add_stone(uid, 1000)
    await sect.create(uid, "战宗", now=1000)
    base = await character.stats(await character.get(uid))

    res = await sect_war.capture(uid, "altar", score=20, now=WAR_OPEN)
    buffed = await character.stats(await character.get(uid))
    raw = base["atk"]

    assert res["status"] == "ok"
    assert buffed["atk"] > base["atk"]
    assert buffed["atk"] <= int(raw * (1 + BUFFS.ATTACK_PCT_CAP))


@pytest.mark.asyncio
async def test_sect_war_capture_uses_unbounded_guard_combat(temp_db, monkeypatch):
    uid = 9620
    await character.create(uid, "blood-war")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    assert (await sect.create(uid, "血战宗", now=1000))["status"] == "ok"
    seen = {}

    def fake_simulate(player, guard, **kwargs):
        seen.update(kwargs)
        return {"winner": player, "log": ["⚔️ 道友 对阵 据点守卫！", "🏆 道友 胜！"],
                "a_hp": player.hp, "d_hp": 0, "rounds": 31, "reason": "defeat"}

    monkeypatch.setattr(sect_war, "simulate", fake_simulate)

    res = await sect_war.capture(uid, "altar", now=WAR_OPEN)

    assert res["status"] == "ok"
    assert seen["max_rounds"] is None


@pytest.mark.asyncio
async def test_sect_war_closed_outside_window(temp_db):
    uid = 9613
    await character.create(uid, "closed")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "时窗宗", now=1000)

    # now=1000 为周四上午，窗口外。
    closed = await sect_war.capture(uid, "altar", now=1000)
    opened = await sect_war.capture(uid, "altar", now=WAR_OPEN)

    assert closed["status"] == "closed"
    assert opened["status"] == "ok"


@pytest.mark.asyncio
async def test_sect_war_rejects_no_stamina_before_combat_and_records_window(temp_db):
    uid = 9634
    await character.create(uid, "tired-warrior")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "疲兵宗", now=1000)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (0, WAR_OPEN - (sect_war.CFG.WAR_STAMINA_COST - 1) * settle.STAMINA_REGEN_SECONDS, uid))

    res = await sect_war.capture(uid, "altar", now=WAR_OPEN)
    row = await db.fetchone("SELECT stamina, stamina_at FROM characters WHERE user_id=?", (uid,))
    window = await db.fetchone(
        "SELECT kind, source_key, start_at, finish_at FROM activity_windows WHERE user_id=?",
        (uid,))
    score = await db.fetchone(
        "SELECT COALESCE(SUM(score), 0) AS s FROM sect_outposts WHERE outpost_key='altar'")

    assert res["status"] == "no_stamina"
    assert res["have"] == sect_war.CFG.WAR_STAMINA_COST - 1
    assert row["stamina"] == sect_war.CFG.WAR_STAMINA_COST - 1
    assert window["kind"] == "sect_war"
    assert window["source_key"] == "altar"
    assert window["finish_at"] - window["start_at"] == sect_war.CFG.WAR_NO_STAMINA_WINDOW_SECONDS
    assert score["s"] == 0


@pytest.mark.asyncio
async def test_sect_war_settles_stamina_regen_before_cost(temp_db):
    uid = 9635
    await character.create(uid, "rested-warrior")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "回气宗", now=1000)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (0, WAR_OPEN - sect_war.CFG.WAR_STAMINA_COST * settle.STAMINA_REGEN_SECONDS, uid))

    res = await sect_war.capture(uid, "altar", now=WAR_OPEN)
    row = await db.fetchone("SELECT stamina, stamina_at FROM characters WHERE user_id=?", (uid,))

    assert res["status"] == "ok"
    assert row["stamina"] == 0
    assert row["stamina_at"] == WAR_OPEN


@pytest.mark.asyncio
async def test_sect_war_success_costs_stamina_and_records_activity_window(temp_db):
    uid = 9636
    await character.create(uid, "window-warrior")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "行军宗", now=1000)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (sect_war.CFG.WAR_STAMINA_COST + 5, WAR_OPEN, uid))

    res = await sect_war.capture(uid, "altar", now=WAR_OPEN)
    row = await db.fetchone("SELECT stamina FROM characters WHERE user_id=?", (uid,))
    window = await db.fetchone(
        "SELECT kind, source_key, start_at, finish_at FROM activity_windows WHERE user_id=?",
        (uid,))

    assert res["status"] == "ok"
    assert row["stamina"] == 5
    assert window["kind"] == "sect_war"
    assert window["source_key"] == "altar"
    assert window["finish_at"] - window["start_at"] == sect_war.CFG.WAR_ACTION_DURATION_SECONDS


@pytest.mark.asyncio
async def test_sect_war_defeat_still_costs_stamina_and_records_window(temp_db):
    uid = 9637
    await character.create(uid, "failed-warrior")
    await character.set_progress(uid, 1, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "败战宗", now=1000)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (sect_war.CFG.WAR_STAMINA_COST + 3, WAR_OPEN, uid))

    res = await sect_war.capture(uid, "altar", now=WAR_OPEN)
    row = await db.fetchone("SELECT stamina FROM characters WHERE user_id=?", (uid,))
    window = await db.fetchone(
        "SELECT kind, source_key FROM activity_windows WHERE user_id=?",
        (uid,))

    assert res["status"] == "defeated"
    assert row["stamina"] == 3
    assert window["kind"] == "sect_war"
    assert window["source_key"] == "altar"


@pytest.mark.asyncio
async def test_sect_war_combat_exception_does_not_cost_stamina(temp_db, monkeypatch):
    uid = 9638
    await character.create(uid, "fault-warrior")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "断线宗", now=1000)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
        (sect_war.CFG.WAR_STAMINA_COST + 7, WAR_OPEN, uid))

    def boom(*_args, **_kwargs):
        raise RuntimeError("combat interrupted")

    monkeypatch.setattr(sect_war, "simulate", boom)

    with pytest.raises(RuntimeError):
        await sect_war.capture(uid, "altar", now=WAR_OPEN)
    row = await db.fetchone("SELECT stamina FROM characters WHERE user_id=?", (uid,))
    window = await db.fetchone("SELECT 1 FROM activity_windows WHERE user_id=?", (uid,))
    score = await db.fetchone(
        "SELECT COALESCE(SUM(score), 0) AS s FROM sect_outposts WHERE outpost_key='altar'")

    assert row["stamina"] == sect_war.CFG.WAR_STAMINA_COST + 7
    assert window is None
    assert score["s"] == 0


@pytest.mark.asyncio
async def test_sect_war_new_season_resets_unsettled_outpost_score(temp_db, monkeypatch):
    uid = 9639
    await character.create(uid, "season-warrior")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "换季宗", now=1000)
    member = await db.fetchone("SELECT sect_id FROM sect_members WHERE user_id=?", (uid,))
    await db.execute(
        "INSERT INTO sect_outposts(sect_id, outpost_key, score, season, updated_at) "
        "VALUES(?, 'altar', 99, '1999-01', ?)",
        (member["sect_id"], WAR_OPEN - 1000))

    def fake_simulate(player, _guard, **_kwargs):
        return {"winner": player, "a_hp": player.hp, "d_hp": 0, "rounds": 1}

    monkeypatch.setattr(sect_war, "simulate", fake_simulate)

    res = await sect_war.capture(uid, "altar", score=20, now=WAR_OPEN)
    row = await db.fetchone(
        "SELECT score, season FROM sect_outposts WHERE sect_id=? AND outpost_key='altar'",
        (member["sect_id"],))

    assert res["status"] == "ok"
    assert row["score"] == 20
    assert row["season"] != "1999-01"


@pytest.mark.asyncio
async def test_sect_can_hold_multiple_outposts(temp_db):
    uid = 9614
    await character.create(uid, "multi")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "多据点宗", now=1000)

    await sect_war.capture(uid, "altar", now=WAR_OPEN)
    await sect_war.capture(uid, "mine", now=WAR_OPEN)
    bonuses = await sect_war.bonuses_for_user(uid)

    # 两个据点 buff 并存：祭坛 stat_pct + 矿脉 drop_pct。
    assert bonuses.get("stat_pct") == 0.05
    assert bonuses.get("drop_pct") == 0.05


@pytest.mark.asyncio
async def test_sect_outpost_seclusion_buff_improves_gain(temp_db):
    uid = 9604
    await character.create(uid, "cave")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "洞府宗", now=1000)
    await sect_war.capture(uid, "cave", now=WAR_OPEN)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))

    plain = 9605
    await character.create(plain, "plain")
    await character.set_progress(plain, 4, 0, 0)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (plain,))

    await character.start_seclusion(uid, now=2000)
    with_buff = await character.collect_seclusion(uid, now=5600)
    await character.start_seclusion(plain, now=2000)
    without_buff = await character.collect_seclusion(plain, now=5600)

    assert with_buff["gained"] > without_buff["gained"]


@pytest.mark.asyncio
async def test_sect_war_capture_requires_beating_guard(temp_db):
    """R-P0-2：低境界成员打不过据点守卫 → 无积分（capture 必须经战斗）。"""
    uid = 9620
    await character.create(uid, "weak")
    await character.set_progress(uid, 1, 0, 0)  # 炼气期，远不敌守卫
    await character.add_stone(uid, 1000)
    await sect.create(uid, "弱宗", now=1000)

    res = await sect_war.capture(uid, "altar", now=WAR_OPEN)

    assert res["status"] == "defeated"
    row = await db.fetchone(
        "SELECT COALESCE(SUM(score),0) AS s FROM sect_outposts WHERE outpost_key='altar'")
    assert row["s"] == 0


@pytest.mark.asyncio
async def test_sect_war_season_settles_top_sect_once(temp_db):
    """R-P0-2：据点积分有消费方——赛季结算向夺魁宗门成员发绑定道行，且幂等。"""
    uid = 9621
    await character.create(uid, "champ")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, 1000)
    await sect.create(uid, "夺魁宗", now=1000)
    await sect_war.capture(uid, "altar", now=WAR_OPEN)
    before = (await character.get(uid)).daohang

    res = await sect_war.settle_season(now=WAR_OPEN)
    assert res["status"] == "ok"
    assert res["members"] == 1
    after = (await character.get(uid)).daohang
    assert after == before + sect_war.CFG.WAR_SEASON_DAOHANG_REWARD

    # 幂等：重复结算不再发放。
    again = await sect_war.settle_season(now=WAR_OPEN)
    assert again["status"] == "settled"
    assert (await character.get(uid)).daohang == after


@pytest.mark.asyncio
async def test_activity_shop_exchanges_material_for_baoming(temp_db):
    """R-P1-5：活动商店消耗活动材料兑保命符（绑定，不入坊市）。"""
    uid = 9630
    await character.create(uid, "shop")
    await character.add_item(uid, "天魔令", 5, bound=1)

    res = await weekly_events.exchange(uid, "baoming", now=1000)

    assert res["status"] == "ok" and res["item"] == "保命符"
    assert await character.item_qty(uid, "保命符", bound=1) == 1
    assert await character.item_qty(uid, "天魔令") == 3  # 扣 2


def test_activity_shop_offer_config_covers_first_reward_set():
    """#48：首批活动商店覆盖保命符、转修令、道途材料和飞升点兑换。"""
    from config.items import ITEMS

    assert W.SHOP_OFFERS["baoming"]["reward_item"] == "保命符"
    assert W.SHOP_OFFERS["switch_token"]["reward_item"] == "转修令"
    assert W.SHOP_OFFERS["path_material"]["reward_item"] == "天外残玉"
    assert W.SHOP_OFFERS["ascension"]["reward_kind"] == "ascension"
    for offer in W.SHOP_OFFERS.values():
        assert offer["material_cost"] > 0
        assert offer["reward_qty"] > 0
        if offer["reward_kind"] == "item":
            assert offer["reward_item"] in ITEMS


@pytest.mark.asyncio
async def test_activity_shop_exchanges_material_for_bound_switch_token(temp_db):
    uid = 9633
    await character.create(uid, "switch-shop")
    await character.add_item(uid, "剑冢铁", 4, bound=1)

    res = await weekly_events.exchange(uid, "switch_token", now=1000)

    assert res["status"] == "ok" and res["item"] == "转修令"
    assert await character.item_qty(uid, "转修令", bound=1) == 1
    assert await character.item_qty(uid, "转修令", bound=0) == 0


@pytest.mark.asyncio
async def test_activity_shop_exchanges_material_for_ascension_point(temp_db):
    """R-P1-3 源之四：活动材料兑飞升点。"""
    uid = 9631
    await character.create(uid, "shop2")
    await character.add_item(uid, "丹霞玉", 3, bound=1)

    res = await weekly_events.exchange(uid, "ascension", now=1000)

    assert res["status"] == "ok" and res["kind"] == "ascension"
    from services import ascension
    assert (await ascension.get(uid))["points"] == res["qty"]


@pytest.mark.asyncio
async def test_activity_shop_rejects_when_material_short(temp_db):
    uid = 9632
    await character.create(uid, "poor")
    await character.add_item(uid, "天魔令", 1, bound=1)
    res = await weekly_events.exchange(uid, "baoming", now=1000)
    assert res["status"] == "no_material"


@pytest.mark.asyncio
async def test_huashen_world_boss_grants_ascension_points_to_top_ranks(temp_db):
    """R-P1-3 源之三：化神世界 Boss 前列按名次发飞升点。"""
    from services import ascension, world_boss

    cfg = world_boss._boss_cfg("huashen")
    assert cfg.get("realm") == 4
    boss_id = 1
    ranked = []
    for i, dmg in enumerate((3000, 2000, 1000, 500)):
        uid = 9640 + i
        await character.create(uid, f"raider{i}")
        await db.execute(
            "INSERT INTO world_boss_damage(boss_id, user_id, damage) VALUES(?,?,?)",
            (boss_id, uid, dmg))
        ranked.append(uid)

    async with db.transaction() as conn:
        rewards = await world_boss._distribute(conn, boss_id, cfg)

    # 前三名各得 3/2/1 飞升点，第四名无。
    assert [r["ascension_points"] for r in rewards] == [3, 2, 1, 0]
    assert (await ascension.get(ranked[0]))["points"] == 3
    assert (await ascension.get(ranked[3]))["points"] == 0


@pytest.mark.asyncio
async def test_season_reward_once_and_no_trade_materials(temp_db):
    uid = 9606
    await character.create(uid, "season")

    first = await season.claim(uid, now=1000)
    second = await season.claim(uid, now=1001)
    row = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (uid,))

    assert first["status"] == "ok"
    assert first["title"]
    assert second["status"] == "claimed"
    assert row["daohang"] == season.SEASON_DAOHANG_REWARD


@pytest.mark.asyncio
async def test_season_settle_monthly_only_rewards_participants(temp_db):
    fighter, idler = 9608, 9609
    await character.create(fighter, "fighter")
    await character.create(idler, "idler")
    # fighter 参与过天梯（有胜负记录），idler 没有。
    async with db.transaction() as conn:
        await pvp.ensure_rating(conn, fighter)
        await conn.execute("UPDATE pvp_ratings SET wins=1 WHERE user_id=?", (fighter,))

    granted = await season.settle_monthly(now=1000)
    again = await season.settle_monthly(now=1001)

    assert fighter in granted
    assert idler not in granted
    assert again == []   # 同赛季幂等，不重复发放
    frow = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (fighter,))
    irow = await db.fetchone("SELECT daohang FROM characters WHERE user_id=?", (idler,))
    assert frow["daohang"] == season.SEASON_DAOHANG_REWARD
    assert irow["daohang"] == 0
