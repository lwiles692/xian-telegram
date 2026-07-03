import pytest
import pytest_asyncio

from config.dungeons import DUNGEONS
from config.items import ITEMS
from config.maps import MAPS
from config.recipes import RECIPES
from config.shop import SHOP_ITEMS
from models import db
from services import character, crafting, items


YUANYING_PAPERS = {
    "天魔刃图纸": "forge_yuanying_blade",
    "战魂甲图纸": "forge_yuanying_armor",
    "古战佩图纸": "forge_yuanying_accessory",
}

HUASHEN_BRANCH_PAPERS = {
    "星河幡图纸": "forge_huashen_banner",
    "星陨袍图纸": "forge_huashen_robe",
    "幽都铃图纸": "forge_huashen_bell",
}


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "issue65-equipment.db"))
    try:
        yield
    finally:
        await db.close_db()


def test_issue65_equipment_configs_exist():
    expected = {
        "天魔刃": ("weapon", "宝", {"atk": 85, "crit": 7}),
        "战魂甲": ("armor", "宝", {"hp": 360, "df": 60}),
        "古战佩": ("accessory", "宝", {"mp": 115, "spd": 15}),
        "星河幡": ("weapon", "玄", {"atk": 340, "mp": 160, "crit": 30}),
        "星陨袍": ("armor", "玄", {"hp": 1450, "df": 250, "spd": 35}),
        "幽都铃": ("accessory", "玄", {"mp": 540, "spd": 50}),
    }

    for key, (slot, tier, bonus) in expected.items():
        item = ITEMS[key]
        assert item["type"] == "equipment"
        assert item["slot"] == slot
        assert item["tier"] == tier
        assert item["bonus"] == bonus

    assert ITEMS["战魂甲"]["tribulation_shield"] == 90
    assert ITEMS["星陨袍"]["tribulation_shield"] == 190
    assert ITEMS["古战佩"]["breakthrough_rate"] == 0.035
    assert ITEMS["幽都铃"]["breakthrough_rate"] == 0.035


def test_issue65_recipe_configs_consume_rare_materials_and_are_not_shop_shortcuts():
    for paper, recipe_key in {**YUANYING_PAPERS, **HUASHEN_BRANCH_PAPERS}.items():
        assert ITEMS[paper]["type"] == "recipe"
        assert ITEMS[paper]["recipe"] == recipe_key
        assert paper not in SHOP_ITEMS
        assert RECIPES[recipe_key]["default"] is False

    assert 900 <= RECIPES["forge_yuanying_blade"]["stone"] <= 1100
    assert {"雷纹玄铁", "天魔残页", "古战魂晶", "器魂"} <= set(
        RECIPES["forge_yuanying_blade"]["materials"])
    assert {"白骨精华", "腐泽妖核", "古战魂晶", "器魂"} <= set(
        RECIPES["forge_yuanying_armor"]["materials"])
    assert {"阴风石", "幽冥草", "劫火残晶", "天魔残页", "器魂"} <= set(
        RECIPES["forge_yuanying_accessory"]["materials"])

    for recipe_key in HUASHEN_BRANCH_PAPERS.values():
        assert 2000 <= RECIPES[recipe_key]["stone"] <= 2300
    assert {"星陨砂", "天外残玉", "化神丹残方", "器魂"} <= set(
        RECIPES["forge_huashen_banner"]["materials"])
    assert {"星陨砂", "幽都魂晶", "天外残玉", "器魂"} <= set(
        RECIPES["forge_huashen_robe"]["materials"])
    assert {"幽都魂晶", "天外残玉", "化神丹残方", "器魂"} <= set(
        RECIPES["forge_huashen_bell"]["materials"])


def test_issue65_blueprints_drop_from_intended_content():
    yuanying_papers = set(YUANYING_PAPERS)
    huashen_branch_papers = set(HUASHEN_BRANCH_PAPERS)
    tianxu_drops = {drop[0] for drop in DUNGEONS["tianxu"]["drops"]}
    tianmo_drops = {drop[0] for drop in MAPS["天魔古原"]["drops"]}
    taixu_drops = {drop[0] for drop in DUNGEONS["taixu"]["drops"]}

    assert yuanying_papers <= tianxu_drops
    assert yuanying_papers <= tianmo_drops
    assert huashen_branch_papers <= taixu_drops


@pytest.mark.asyncio
async def test_issue65_blueprints_unlock_and_forge_equipment_instances(temp_db):
    uid = 6501
    await character.create(uid, "smith65")

    for idx, (paper, recipe_key) in enumerate({**YUANYING_PAPERS, **HUASHEN_BRANCH_PAPERS}.items()):
        recipe = RECIPES[recipe_key]
        await character.set_progress(uid, recipe["realm"], 0, 0)
        await character.add_stone(uid, recipe["stone"])
        await character.add_item(uid, paper, 1)
        for material, qty in recipe["materials"].items():
            await character.add_item(uid, material, qty)

        learned = await items.use(uid, paper, now=1000 + idx)
        assert learned["status"] == "recipe_ok"
        known = await crafting.known_recipe_keys(uid)
        assert recipe_key in known

        started = await crafting.start_job(uid, recipe_key, now=2000 + idx * 5000)
        assert started["status"] == "started"

        collected = await crafting.collect_ready(uid, now=started["finish_at"])
        output_key = recipe["output"]["key"]
        assert any(item["name"] == ITEMS[output_key]["name"] for item in collected)
        assert any(inst["base_key"] == output_key for inst in await character.item_instances(uid))
