import copy

import pytest
import pytest_asyncio

from config import bosses
from config import realms as R
from models import db
from services import character, daily, pvp, sect, world_boss


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "m3-test.db"))
    try:
        yield
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_pvp_duel_updates_ratings_and_reward(temp_db):
    a, b = 3001, 3002
    await character.create(a, "attacker")
    await character.create(b, "defender")
    await character.set_progress(a, 1, R.num_stages(1) - 1, 0)
    await character.set_progress(b, 1, 0, 0)

    res = await pvp.duel(a, b, now=1000)
    assert res["status"] == "ok"
    rows = await pvp.top()
    assert {row["user_id"] for row in rows} == {a, b}
    assert any(row["rating"] != 1000 for row in rows)
    assert sum(row["reputation"] for row in rows) == pvp.WIN_REPUTATION + pvp.LOSS_REPUTATION
    # PvP 不再发可重复即时灵石；首胜只可能触发一次性成就奖励。
    assert (await character.get(a)).spirit_stone in {100, 220}


@pytest.mark.asyncio
async def test_pvp_uses_duel_ban_and_resolves_slow_fights(temp_db, monkeypatch):
    a, b = 3231, 3232
    await character.create(a, "attacker")
    await character.create(b, "defender")

    async def slow_combatant(user_id: int, name: str):
        return pvp.Combatant(
            name=name, hp=200, mp=100, atk=6, df=300,
            spd=30 if user_id == a else 10, crit=0, skills=["普攻"])

    seen = {}
    original_simulate = pvp.simulate

    def capture_simulate(*args, **kwargs):
        seen.update(kwargs)
        return original_simulate(*args, **kwargs)

    monkeypatch.setattr(pvp, "_combatant", slow_combatant)
    monkeypatch.setattr(pvp, "simulate", capture_simulate)

    res = await pvp.duel(a, b, now=1000)
    rows = await pvp.top()
    daily = await db.fetchone("SELECT daily_count FROM pvp_ratings WHERE user_id=?", (a,))
    pairs = await db.fetchall("SELECT * FROM pvp_daily_pairs")

    assert res["status"] == "ok"
    assert seen["max_rounds"] == pvp.PVP_MAX_ROUNDS
    assert seen["rules"] is pvp.PVP_COMBAT_RULES
    assert res["rounds"] > 30
    assert res["rounds"] <= pvp.PVP_MAX_ROUNDS
    assert res["finish_reason"] in ("defeat", "double_down")
    assert res["win"] in (True, False)
    assert res["rating_delta"] != 0
    assert res["reputation_gain"] in (pvp.WIN_REPUTATION, pvp.LOSS_REPUTATION)
    assert any(row["wins"] == 1 for row in rows if row["user_id"] in (a, b))
    assert any(row["losses"] == 1 for row in rows if row["user_id"] in (a, b))
    assert daily["daily_count"] == 1
    assert len(pairs) == 1


@pytest.mark.asyncio
async def test_pvp_same_opponent_counts_reputation_once_per_day(temp_db):
    a, b = 3201, 3202
    await character.create(a, "ace")
    await character.create(b, "rook")
    await character.set_progress(a, 1, R.num_stages(1) - 1, 0)
    await character.set_progress(b, 1, 0, 0)

    first = await pvp.duel(a, b, now=1000)
    second = await pvp.duel(a, b, now=1500)  # 同日同对手
    assert first["reputation_counted"] is True
    assert second["reputation_counted"] is False and second["reputation_gain"] == 0


@pytest.mark.asyncio
async def test_pvp_allows_secluded_players(temp_db):
    a, b = 3203, 3204
    await character.create(a, "meditating_attacker")
    await character.create(b, "meditating_defender")
    await db.execute("UPDATE characters SET seclusion_at=? WHERE user_id=?", (900, a))
    await db.execute("UPDATE characters SET seclusion_at=? WHERE user_id=?", (901, b))

    preview = await pvp.preview_duel(a, b)
    res = await pvp.duel(a, b, now=1000)

    assert preview["status"] == "ok"
    assert res["status"] == "ok"
    assert (await character.get(a)).seclusion_at == 900
    assert (await character.get(b)).seclusion_at == 901


@pytest.mark.asyncio
async def test_pvp_weekly_pool_settles_by_rank_and_resets(temp_db):
    a, b = 3211, 3212
    await character.create(a, "champ")
    await character.create(b, "rival")
    await character.set_progress(a, 1, R.num_stages(1) - 1, 0)
    await character.set_progress(b, 1, 0, 0)
    # 跨天多场，积累本周有效声望（同对手每日仅计一次）。
    for d in range(3):
        await pvp.duel(a, b, now=1000 + d * 86400)

    results = await pvp.settle_weekly(now=1000)
    assert results and results[0]["stone"] > 0
    assert (await character.get(a)).spirit_stone > 100   # 榜首拿到奖池灵石
    row = await db.fetchone("SELECT week_reputation FROM pvp_ratings WHERE user_id=?", (a,))
    assert row["week_reputation"] == 0                   # 结算后清零


@pytest.mark.asyncio
async def test_pvp_weekly_pool_normalizes_for_small_participant_counts(temp_db):
    a, b = 3221, 3222
    await character.create(a, "solo")
    await character.create(b, "sparring")
    await character.set_progress(a, 1, R.num_stages(1) - 1, 0)
    await character.set_progress(b, 1, 0, 0)
    await pvp.duel(a, b, now=1000)

    pool = 101
    before = {
        uid: (await character.get(uid)).spirit_stone
        for uid in (a, b)
    }
    results = await pvp.settle_weekly(now=1000, pool=pool)
    after = {
        uid: (await character.get(uid)).spirit_stone
        for uid in (a, b)
    }

    assert sum(row["stone"] for row in results) == pool
    assert sum(after[uid] - before[uid] for uid in (a, b)) == pool


@pytest.mark.asyncio
async def test_pvp_duel_shows_real_names(temp_db):
    a, b = 3101, 3102
    await character.create(a, "alice")
    await character.create(b, "bob")
    await character.set_progress(a, 1, R.num_stages(1) - 1, 0)
    await character.set_progress(b, 1, 0, 0)

    res = await pvp.duel(a, b, now=1000)
    assert res["status"] == "ok"
    assert res["attacker_name"] == "alice"
    assert res["defender_name"] == "bob"
    joined = "\n".join(res["log"])
    assert "道友" not in joined and "对手" not in joined
    assert "alice" in joined and "bob" in joined

    # 群昵称（无库内 @username）应作为显示名透传进战斗日志。
    res2 = await pvp.duel(a, b, now=1000, attacker_name="剑无尘")
    assert res2["attacker_name"] == "剑无尘"
    assert "剑无尘" in "\n".join(res2["log"])


@pytest.mark.asyncio
async def test_pvp_duel_falls_back_to_user_ids(temp_db):
    a, b = 3111, 3112
    await character.create(a, "")
    await character.create(b, "")
    await character.set_progress(a, 1, R.num_stages(1) - 1, 0)
    await character.set_progress(b, 1, 0, 0)

    res = await pvp.duel(a, b, now=1000)

    assert res["status"] == "ok"
    assert res["attacker_name"] == str(a)
    assert res["defender_name"] == str(b)
    joined = "\n".join(res["log"])
    assert "道友" not in joined and "对手" not in joined
    assert str(a) in joined and str(b) in joined


@pytest.mark.asyncio
async def test_world_boss_challenge_defeats_and_rewards(temp_db):
    original = copy.deepcopy(bosses.WORLD_BOSSES["zhuji"])
    bosses.WORLD_BOSSES["zhuji"]["total_hp"] = 1
    bosses.WORLD_BOSSES["zhuji"]["stone_pool"] = 100
    try:
        uid = 3003
        await character.create(uid, "bosskiller")
        await character.set_progress(uid, 1, R.num_stages(1) - 1, 0)
        await db.execute(
            "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
            (200, 1000, uid))

        res = await world_boss.challenge(-100, uid, now=1000)
        assert res["status"] == "ok"
        assert res["defeated"]
        assert (await world_boss.challenge(-100, uid, now=1001))["status"] == "defeated"
        assert await character.item_qty(uid, "妖丹") >= 8
        assert (await character.get(uid)).spirit_stone >= 200
    finally:
        bosses.WORLD_BOSSES["zhuji"] = original


@pytest.mark.asyncio
async def test_world_boss_small_groups_share_special_drops(temp_db):
    chat_id = -3300
    uids = [330001, 330002, 330003]
    for idx, uid in enumerate(uids, start=1):
        await character.create(uid, f"boss{idx}")

    boss = await world_boss.ensure_active(chat_id, now=1000)
    for uid, damage in zip(uids, (300, 200, 100)):
        await db.execute(
            "INSERT INTO world_boss_damage(boss_id, user_id, damage) VALUES(?,?,?)",
            (boss["id"], uid, damage))

    res = await world_boss.status(chat_id, now=boss["expire_at"] + 1)

    assert res["status"] == "expired"
    assert await character.item_qty(uids[0], "金丹") > 0
    assert await character.item_qty(uids[1], "金丹") > 0
    assert await character.item_qty(uids[2], "金丹") == 0
    for key, total in bosses.WORLD_BOSSES["zhuji"]["drops"].items():
        assert sum([await character.item_qty(uid, key) for uid in uids]) == total


@pytest.mark.asyncio
async def test_world_boss_large_groups_do_not_inflate_configured_drops(temp_db):
    chat_id = -3310
    uids = [331000 + idx for idx in range(15)]
    for idx, uid in enumerate(uids, start=1):
        await character.create(uid, f"raid{idx}")

    boss = await world_boss.ensure_active(chat_id, now=1000)
    for idx, uid in enumerate(uids):
        await db.execute(
            "INSERT INTO world_boss_damage(boss_id, user_id, damage) VALUES(?,?,?)",
            (boss["id"], uid, 1000 - idx))

    res = await world_boss.status(chat_id, now=boss["expire_at"] + 1)

    assert res["status"] == "expired"
    slots = len(uids) // 3
    for key, total in bosses.WORLD_BOSSES["zhuji"]["drops"].items():
        expected = (total // slots) * slots if total >= slots else total
        assert sum([await character.item_qty(uid, key) for uid in uids]) == expected


def test_world_boss_reward_text_summarizes_drop_quantities():
    text = world_boss.reward_text([
        {"rank": 1, "user_id": 1, "stone": 100, "drops": {"妖丹": 2, "金丹": 1}},
        {"rank": 2, "user_id": 2, "stone": 80, "drops": {"妖丹": 1}},
        {"rank": 3, "user_id": 3, "stone": 50, "drops": {}},
    ])

    assert "前列另分 妖丹×3、金丹×1" in text


@pytest.mark.asyncio
async def test_world_boss_hp_scales_by_known_group_cultivators(temp_db):
    solo_chat = -3301
    solo_uid = 330101
    await character.create(solo_uid, "solo")
    await world_boss.remember_chat(solo_chat, "独行群", now=1000)
    assert await world_boss.remember_cultivator(solo_chat, solo_uid, now=1000)

    solo = await world_boss.ensure_active(solo_chat, now=1000)

    full_hp = bosses.WORLD_BOSSES["zhuji"]["total_hp"]
    assert solo["cultivator_count"] == 1
    assert solo["total_hp"] == full_hp // bosses.WORLD_BOSS_FULL_HP_CULTIVATORS
    assert solo["remaining_hp"] == solo["total_hp"]

    many_chat = -3302
    await world_boss.remember_chat(many_chat, "十人群", now=1000)
    for idx in range(bosses.WORLD_BOSS_FULL_HP_CULTIVATORS):
        uid = 330200 + idx
        await character.create(uid, f"dao{idx}")
        await world_boss.remember_cultivator(many_chat, uid, now=1000)

    many = await world_boss.ensure_active(many_chat, now=1000)

    assert many["cultivator_count"] == bosses.WORLD_BOSS_FULL_HP_CULTIVATORS
    assert many["total_hp"] == full_hp


@pytest.mark.asyncio
async def test_world_boss_tier_uses_known_group_cultivator_realms(temp_db):
    chat_id = -3303
    await world_boss.remember_chat(chat_id, "金丹群", now=1000)
    for idx, realm in enumerate((1, 2, 2), start=1):
        uid = 330300 + idx
        await character.create(uid, f"tier{idx}")
        await character.set_progress(uid, realm, 0, 0)
        await world_boss.remember_cultivator(chat_id, uid, now=1000)

    boss = await world_boss.ensure_active(chat_id, now=1000)

    assert boss["boss_key"] == "jindan"
    assert boss["cultivator_count"] == 3
    assert boss["total_hp"] == int(round(
        bosses.WORLD_BOSSES["jindan"]["total_hp"]
        * 3 / bosses.WORLD_BOSS_FULL_HP_CULTIVATORS))


@pytest.mark.asyncio
async def test_world_boss_legacy_key_remains_readable(temp_db):
    uid = 3023
    chat_id = -3023
    await character.create(uid, "oldboss")
    await db.execute(
        "INSERT INTO world_boss(chat_id, boss_key, total_hp, remaining_hp, spawn_at, expire_at, status) "
        "VALUES(?,?,?,?,?,?, 'alive')",
        (chat_id, "ancient_dragon", 10, 10, 1000, 1000 + 7200))

    res = await world_boss.status(chat_id, now=1001)

    assert res["status"] == "alive"
    assert res["boss"]["boss_key"] == "ancient_dragon"


@pytest.mark.asyncio
async def test_sect_create_task_and_redeem(temp_db):
    uid = 3004
    await character.create(uid, "leader")
    await character.set_progress(uid, 1, 0, 0)
    await character.add_stone(uid, 500)

    assert (await sect.create(uid, "青云门", now=1000))["status"] == "ok"
    assert (await sect.task(uid, now=1000))["status"] == "ok"
    assert (await sect.task(uid, now=1001))["status"] == "done"
    await db.execute(
        "UPDATE sect_members SET contribution=? WHERE user_id=?",
        (40, uid))
    res = await sect.redeem(uid, "烈火诀残页")
    assert res["status"] == "ok"
    assert await character.item_qty(uid, "烈火诀残页") == 1


@pytest.mark.asyncio
async def test_daily_checkin_once_per_day(temp_db):
    uid = 3005
    await character.create(uid, "daily")
    first = await daily.checkin(uid, now=1000)
    second = await daily.checkin(uid, now=1001)

    assert first["status"] == "ok"
    assert second["status"] == "done"
    assert first["streak"] == second["streak"] == 1


@pytest.mark.asyncio
async def test_daily_checkin_grants_bound_huashen_aid_at_yuanying_full(temp_db):
    uid = 3015
    await character.create(uid, "daily-huashen")
    last_yy = R.num_stages(3) - 1
    await character.set_progress(uid, 3, last_yy, R.advance_cost(3, last_yy))

    first = await daily.checkin(uid, now=1000)
    second = await daily.checkin(uid, now=1001)

    assert first["status"] == "ok"
    assert first["extra_items"] == [{
        "item": "化神丹",
        "qty": 1,
        "bound": 1,
        "reason": "yuanying_full_aid",
    }]
    assert second["status"] == "done"
    assert await character.item_qty(uid, "化神丹", bound=1) == 1
    assert await character.item_qty(uid, "化神丹", bound=0) == 0


@pytest.mark.asyncio
async def test_daily_huashen_aid_requires_full_cultivation_and_does_not_stockpile(temp_db):
    last_yy = R.num_stages(3) - 1
    cost = R.advance_cost(3, last_yy)

    not_full = 3016
    await character.create(not_full, "not-full")
    await character.set_progress(not_full, 3, last_yy, cost - 1)
    res = await daily.checkin(not_full, now=1000)
    assert res["status"] == "ok"
    assert res["extra_items"] == []
    assert await character.item_qty(not_full, "化神丹") == 0

    already_has = 3017
    await character.create(already_has, "already-has")
    await character.set_progress(already_has, 3, last_yy, cost)
    await character.add_item(already_has, "化神丹", 1, bound=0)
    res = await daily.checkin(already_has, now=1000)
    assert res["status"] == "ok"
    assert res["extra_items"] == []
    assert await character.item_qty(already_has, "化神丹", bound=0) == 1
    assert await character.item_qty(already_has, "化神丹", bound=1) == 0
