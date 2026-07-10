from __future__ import annotations

import pytest
import pytest_asyncio

from config import recipes as REC
from config import shop as SHOP
from config.bosses import WORLD_BOSSES
from config.dungeons import DUNGEONS
from config.items import ITEMS, is_tradable
from config.maps import MAPS
from handlers import craft as craft_handler
from models import db
from services import character, crafting, items


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "lianxu-pill.db"))
    try:
        yield
    finally:
        await db.close_db()


def _drop_keys(drops):
    return {drop[0] for drop in drops}


def _button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_lianxu_pill_config_and_huashen_sources():
    assert ITEMS["炼虚丹"]["type"] == "pill"
    assert ITEMS["炼虚丹残方"]["type"] == "material"
    assert ITEMS["炼虚丹方"]["recipe"] == "lianxu_pill"
    assert "炼虚丹" not in SHOP.SHOP_ITEMS
    assert is_tradable("炼虚丹") is False

    recipe = REC.RECIPES["lianxu_pill"]
    assert recipe["realm"] == 4
    assert recipe["default"] is False
    assert recipe["materials"] == {"炼虚丹残方": 4}
    assert recipe["output"] == {"kind": "item", "key": "炼虚丹", "qty": 1, "bound": 1}

    tianwai = _drop_keys(MAPS["天外古墟"]["drops"])
    taixu = _drop_keys(DUNGEONS["taixu"]["drops"])
    assert {"炼虚丹残方", "炼虚丹"} <= tianwai
    assert {"炼虚丹残方", "炼虚丹方"} <= taixu
    assert "炼虚丹残方" in WORLD_BOSSES["huashen"]["drops"]
    assert "炼虚丹" not in WORLD_BOSSES["huashen"]["drops"]


def test_lianxu_equipment_paper_scrap_is_m1_clue_drop():
    assert ITEMS["炼虚装备图纸残页"]["type"] == "material"

    tianwai = _drop_keys(MAPS["天外古墟"]["drops"])
    taixu = _drop_keys(DUNGEONS["taixu"]["drops"])

    assert "炼虚装备图纸残页" in tianwai
    assert "炼虚装备图纸残页" in taixu


@pytest.mark.asyncio
async def test_lianxu_locked_craft_placeholders_are_visible_without_unlocking(temp_db):
    uid = 9802
    await character.create(uid, "望炉客")
    await character.set_progress(uid, 4, 0, 0)

    alchemy_text, alchemy_markup = await craft_handler.render_craft_category(uid, "alchemy")
    forge_text, forge_markup = await craft_handler.render_craft_category(uid, "forge")

    assert "炼虚丹（待解锁）" in alchemy_text
    assert "炼虚丹方" in alchemy_text
    assert "炼虚法宝（待解锁）" in forge_text
    assert "炼虚装备图纸残页" in forge_text
    assert not any("炼虚丹" in text for text in _button_texts(alchemy_markup))
    assert not any("炼虚法宝" in text for text in _button_texts(forge_markup))


@pytest.mark.asyncio
async def test_lianxu_forge_placeholders_turn_into_blueprint_recipes(temp_db):
    uid = 9803
    await character.create(uid, "开炉客")
    await character.set_progress(uid, 5, 0, 0)

    forge_text, forge_markup = await craft_handler.render_craft_category(uid, "forge")

    assert "炼虚法宝（待解锁）" not in forge_text
    assert "太初虚刃图纸" in forge_text
    assert "玄冥空甲图纸" in forge_text
    assert "混沌灵佩图纸" in forge_text
    buttons = _button_texts(forge_markup)
    assert any("太初虚刃图纸" in text for text in buttons)
    assert any("玄冥空甲图纸" in text for text in buttons)
    assert any("混沌灵佩图纸" in text for text in buttons)


@pytest.mark.asyncio
async def test_lianxu_scrap_recipe_outputs_bound_pill(temp_db):
    uid = 9801
    await character.create(uid, "炼丹客")
    await character.set_progress(uid, 4, 0, 0)
    await character.add_stone(uid, REC.RECIPES["lianxu_pill"]["stone"])
    await character.add_item(uid, "炼虚丹残方", 4)
    await character.add_item(uid, "炼虚丹方", 1)

    learned = await items.use(uid, "炼虚丹方", now=1000)
    started = await crafting.start_job(uid, "lianxu_pill", now=1100)
    collected = await crafting.collect_ready(uid, now=1100 + started["seconds"])

    assert learned["status"] == "recipe_ok"
    assert started["status"] == "started"
    assert any(row["name"] == "炼虚丹" and row.get("bound") == 1 for row in collected)
    assert await character.item_qty(uid, "炼虚丹", bound=1) == 1
    assert await character.item_qty(uid, "炼虚丹", bound=0) == 0
    assert await character.item_qty(uid, "炼虚丹残方") == 0
