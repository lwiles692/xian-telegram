from __future__ import annotations

import pytest
import pytest_asyncio

from config import realms as R
from config import bosses
from config.bosses import WORLD_BOSSES, boss_key_for_realm
from config.dungeons import DUNGEONS
from models import db
from services import character, shop, world_boss
from tools import balance_sim as B


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "lianxu-loop-test.db"))
    try:
        yield
    finally:
        await db.close_db()


def test_xukong_dungeon_config_complete():
    d = DUNGEONS["xukong"]

    assert d["name"] == "虚空神殿"
    assert d["realm"] == 5
    assert d["layers"] == 6
    assert d["stamina"] == 70
    assert d["daily_limit"] == 2
    assert d["entry_stone"] == 4000
    assert d["stamina"] * d["daily_limit"] == 140
    assert d["stamina"] * d["daily_limit"] <= R.STAMINA_CAP[5]
    drops = {row[0] for row in d["drops"]}
    assert {"炼虚丹残方", "炼虚装备图纸残页", "混沌残核", "天外残玉", "转修令"} <= drops


def test_xukong_entry_and_full_clear_fraction_targets():
    entry = B.dungeon_clear_fraction(5, 0, "xukong", profile=B.LIANXU_GEARED, n=120)
    full = B.dungeon_clear_fraction(5, R.num_stages(5) - 1, "xukong", profile=B.LIANXU_GEARED, n=120)

    assert 0.40 <= entry <= 0.70
    assert full >= 0.95


def test_xukong_dungeon_economy_stays_under_lianxu_buy_margin():
    cap = shop.first_buy_cost_per_stamina(5) * 0.75
    stone = B.dungeon_stone_per_stamina("xukong")
    value = stone + B.dungeon_drops_sell_per_stamina("xukong")

    assert stone < cap
    assert value < cap
    assert B.best_content_value_per_stamina(5) < shop.first_buy_cost_per_stamina(5)


def test_lianxu_world_boss_config_complete():
    assert boss_key_for_realm(5) == "lianxu"
    boss = WORLD_BOSSES["lianxu"]

    assert boss["name"] == "吞虚魔蟒"
    assert boss["realm"] == 5
    assert boss["duration"] == 2 * 3600
    assert boss["stamina"] == 20
    assert "炼虚丹" not in boss["drops"]
    assert {"炼虚丹残方", "炼虚装备图纸残页", "混沌残核", "天外残玉", "转修令"} <= set(boss["drops"])


def test_lianxu_world_boss_kill_challenges_target_range():
    challenges = B.world_boss_kill_challenges("lianxu", 5, 2, n=120, profile=B.LIANXU_GEARED)
    full = B.world_boss_kill_challenges(
        "lianxu", 5, R.num_stages(5) - 1, n=120, profile=B.LIANXU_GEARED)

    assert 20 <= challenges <= 80
    assert full >= 8


@pytest.mark.asyncio
async def test_lianxu_world_boss_tier_and_small_group_scaling(temp_db):
    chat_id = -5102
    for idx in range(3):
        uid = 510200 + idx
        await character.create(uid, f"lianxu{idx}")
        await character.set_progress(uid, 5, 0, 0)
        assert await world_boss.remember_cultivator(chat_id, uid, now=1000)

    boss = await world_boss.ensure_active(chat_id, now=1000)

    assert boss["boss_key"] == "lianxu"
    assert boss["cultivator_count"] == 3
    assert boss["total_hp"] == int(round(
        bosses.WORLD_BOSSES["lianxu"]["total_hp"] * 3 / bosses.WORLD_BOSS_FULL_HP_CULTIVATORS))
