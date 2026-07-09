from __future__ import annotations

import pytest
import pytest_asyncio

from config import realms as R
from config import bosses
from config.bosses import WORLD_BOSSES, boss_key_for_realm
from config.dungeons import DUNGEONS
from config.items import ITEMS, is_tradable
from models import db
from config.maps import MAPS
from config.recipes import RECIPES
from services import character, crafting, items as item_service, shop, world_boss
from tools import balance_sim as B

LIANXU_BLUEPRINT_RECIPES = {
    "太初虚刃图纸": "lianxu_blade_blueprint",
    "玄冥空甲图纸": "lianxu_armor_blueprint",
    "混沌灵佩图纸": "lianxu_accessory_blueprint",
}
LIANXU_FORGE_RECIPES = {
    "太初虚刃图纸": "forge_lianxu_blade",
    "玄冥空甲图纸": "forge_lianxu_armor",
    "混沌灵佩图纸": "forge_lianxu_accessory",
}


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


def test_lianxu_equipment_configs_and_recipes_exist():
    expected = {
        "太初虚刃": ("weapon", {"atk": 820, "crit": 48, "atk_pct": 0.02}),
        "玄冥空甲": ("armor", {"hp": 4200, "df": 760, "hp_pct": 0.02}),
        "混沌灵佩": ("accessory", {"mp": 900, "spd": 130, "df_pct": 0.015}),
    }

    for key, (slot, bonus) in expected.items():
        item = ITEMS[key]
        assert item["type"] == "equipment"
        assert item["slot"] == slot
        assert item["tier"] == "玄"
        assert item["bonus"] == bonus
    assert ITEMS["玄冥空甲"]["tribulation_shield"] == 320
    assert ITEMS["混沌灵佩"]["breakthrough_rate"] == 0.045

    for paper, blueprint_recipe in LIANXU_BLUEPRINT_RECIPES.items():
        assert ITEMS[paper]["type"] == "recipe"
        assert ITEMS[paper]["recipe"] == LIANXU_FORGE_RECIPES[paper]
        recipe = RECIPES[blueprint_recipe]
        assert recipe["realm"] == 5
        assert recipe["default"] is True
        assert recipe["materials"]["炼虚装备图纸残页"] >= 6
        assert recipe["output"] == {"kind": "item", "key": paper, "qty": 1}

    forge_materials = set()
    for recipe_key in LIANXU_FORGE_RECIPES.values():
        recipe = RECIPES[recipe_key]
        assert recipe["realm"] == 5
        assert recipe["default"] is False
        assert recipe["output"]["key"] in expected
        forge_materials.update(recipe["materials"])
    assert {"雾泽虚砂", "裂海空髓", "混沌残核"} <= forge_materials
    assert is_tradable("混沌残核") is True


def test_lianxu_equipment_sources_include_dungeon_boss_and_hard_map():
    xukong_drops = {drop[0] for drop in DUNGEONS["xukong"]["drops"]}
    hard_map_drops = {drop[0] for drop in MAPS["混沌古狱"]["drops"]}
    boss_drops = set(WORLD_BOSSES["lianxu"]["drops"])

    assert {"太初虚刃图纸", "玄冥空甲图纸", "混沌灵佩图纸"} <= xukong_drops
    assert {"炼虚装备图纸残页", "混沌灵佩图纸"} <= hard_map_drops
    assert {"太初虚刃图纸", "玄冥空甲图纸", "混沌灵佩图纸"} <= boss_drops


def test_lianxu_equipment_profile_keeps_anchor_headroom():
    base = R.base_stats(5, R.num_stages(5) - 1)
    geared = B.build_player_stats(5, R.num_stages(5) - 1, B.LIANXU_EQUIPMENT_PROFILE)
    capped = B.build_player_stats(
        5, R.num_stages(5) - 1,
        {**B.LIANXU_EQUIPMENT_PROFILE, "extra_pct": {"atk": 1.0, "hp": 1.0, "df": 1.0}})

    assert 1.08 <= geared["hp"] / base["hp"] <= 1.16
    assert 1.08 <= geared["atk"] / base["atk"] <= 1.16
    assert 1.05 <= geared["df"] / base["df"] <= 1.14
    assert geared["spd"] / base["spd"] <= 1.08
    assert capped["atk"] > geared["atk"]
    assert capped["hp"] > geared["hp"]
    assert capped["df"] > geared["df"]


@pytest.mark.asyncio
async def test_lianxu_blueprint_scraps_unlock_and_forge_equipment(temp_db):
    uid = 5103
    await character.create(uid, "炼虚器师")
    await character.set_progress(uid, 5, 0, 0)

    for idx, (paper, blueprint_recipe_key) in enumerate(LIANXU_BLUEPRINT_RECIPES.items()):
        forge_recipe_key = LIANXU_FORGE_RECIPES[paper]
        blueprint_recipe = RECIPES[blueprint_recipe_key]
        forge_recipe = RECIPES[forge_recipe_key]
        await character.add_stone(uid, blueprint_recipe["stone"] + forge_recipe["stone"])
        for material, qty in blueprint_recipe["materials"].items():
            await character.add_item(uid, material, qty)

        started = await crafting.start_job(uid, blueprint_recipe_key, now=1000 + idx * 10000)
        collected = await crafting.collect_ready(uid, now=started["finish_at"])
        learned = await item_service.use(uid, paper, now=started["finish_at"] + 1)

        assert started["status"] == "started"
        assert any(row["name"] == ITEMS[paper]["name"] for row in collected)
        assert learned["status"] == "recipe_ok"
        assert forge_recipe_key in await crafting.known_recipe_keys(uid)

        for material, qty in forge_recipe["materials"].items():
            await character.add_item(uid, material, qty)
        forged = await crafting.start_job(uid, forge_recipe_key, now=started["finish_at"] + 100)
        forged_items = await crafting.collect_ready(uid, now=forged["finish_at"])

        output_key = forge_recipe["output"]["key"]
        assert forged["status"] == "started"
        assert any(row["name"] == ITEMS[output_key]["name"] for row in forged_items)
        assert any(inst["base_key"] == output_key for inst in await character.item_instances(uid))
