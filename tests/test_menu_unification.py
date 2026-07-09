import pytest
import pytest_asyncio

from handlers import (ascension as ascension_handler, auction as auction_handler,
                      bag as bag_handler,
                      bonds as bonds_handler,
                      craft as craft_handler, cultivate as cultivate_handler,
                      dao_path as dao_path_handler, dungeon as dungeon_handler,
                      explore as explore_handler, help as help_handler,
                      market as market_handler, me as me_handler,
                      quest as quest_handler, sect as sect_handler,
                      sect_war as sect_war_handler, shop as shop_handler,
                      skills as skills_handler, weekly_events as weekly_handler)
from handlers.common import main_menu, section_back_markup
from models import db
from services import character, market as market_service


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "menu-unification.db"))
    try:
        yield
    finally:
        await db.close_db()


def _datas(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


PRIMARY_NAVS = {
    button.callback_data
    for row in main_menu().inline_keyboard
    for button in row
}


def _assert_compact_top_level_menu(markup):
    datas = set(_datas(markup))

    assert "nav:menu" in datas
    assert not (PRIMARY_NAVS & datas)


@pytest.mark.asyncio
async def test_top_level_feature_pages_do_not_embed_full_main_menu(temp_db):
    """#52：主菜单入口页只展示本页操作和返回主菜单，不再拼完整主菜单。"""
    uid = 5200
    await character.create(uid, "menu-tester")

    pages = [
        ("道行", await me_handler.render_me(uid)),
        ("闭关", await cultivate_handler.render_cultivate(uid)),
        ("历练", await explore_handler.render_menu(uid)),
        ("秘境", await dungeon_handler.render_dungeon(uid)),
        ("炼制", await craft_handler.render_craft(uid)),
        ("功法", await skills_handler.render_skills(uid)),
        ("商店", await shop_handler.render_shop(uid)),
        ("储物袋", await bag_handler.render_bag(uid)),
        ("悬赏", await quest_handler.render_quest(uid)),
        ("师徒", await bonds_handler.render_master(uid)),
        ("宗门", await sect_handler.render_sect(uid)),
        ("道途", await dao_path_handler.render_path(uid)),
        ("飞升", await ascension_handler.render_ascension(uid)),
        ("活动", await weekly_handler.render_weekly(uid)),
        ("坊市", await market_handler.render_market(uid)),
        ("拍卖", await auction_handler.render_auction(uid)),
        ("宗门战", await sect_war_handler.render_sect_war(uid)),
    ]

    for name, (_text, markup) in pages:
        assert markup is not None, name
        _assert_compact_top_level_menu(markup)


@pytest.mark.asyncio
async def test_secondary_pages_keep_contextual_back_links_without_full_menu(temp_db):
    uid = 5201
    await character.create(uid, "submenu-tester")

    secondary_pages = [
        ("商店分类", await shop_handler.render_category(uid, "material"), {"nav:shop"}),
        ("坊市定价", await market_handler.render_listing_editor(uid, "灵草", 100), {"market:cat:sell"}),
        ("宗门商店", await sect_handler.render_sect_shop(uid), {"nav:sect"}),
    ]

    for name, (_text, markup), expected_back_links in secondary_pages:
        datas = set(_datas(markup))
        assert expected_back_links <= datas, name
        assert not ((PRIMARY_NAVS - expected_back_links) & datas), name
        assert "nav:menu" not in datas, name


@pytest.mark.asyncio
async def test_dense_feature_home_pages_link_to_categories_before_actions(temp_db):
    uid = 5202
    seller = 5203
    await character.create(uid, "dense-menu")
    await character.create(seller, "seller")
    await character.set_progress(uid, 1, 0, 0)
    await character.add_item(uid, "灵草", 3)
    await character.add_item(uid, "疗伤丹", 1)
    await character.add_item(uid, "筑基丹", 1)
    await character.add_item(uid, "归元心法残页", 3)
    await character.create_item_instance(uid, "玄铁剑")
    await character.add_item(seller, "星陨砂", 1)
    await market_service.create_listing(seller, "星陨砂", 1, 100, now=1000)

    _text, craft_home = await craft_handler.render_craft(uid)
    craft_home_datas = _datas(craft_home)
    assert {"craft:cat:alchemy", "craft:cat:forge"} <= set(craft_home_datas)
    assert not any(data.startswith("craft:start:") for data in craft_home_datas)
    _text, craft_cat = await craft_handler.render_craft_category(uid, "alchemy")
    assert any(data.startswith("craft:start:") for data in _datas(craft_cat))

    _text, bag_home = await bag_handler.render_bag(uid)
    bag_home_datas = _datas(bag_home)
    assert {"bag:cat:usable", "bag:cat:pill", "bag:cat:material",
            "bag:cat:equipment"} <= set(bag_home_datas)
    assert not any(data.startswith("bag:use:") for data in bag_home_datas)
    _text, bag_cat = await bag_handler.render_bag_category(uid, "usable")
    assert any(data.startswith("bag:use:") for data in _datas(bag_cat))
    pill_text, _markup = await bag_handler.render_bag_category(uid, "pill")
    assert "突破时自动消耗" in pill_text
    equipment_text, _markup = await bag_handler.render_bag_category(uid, "equipment")
    assert "请到「功法」" in equipment_text

    _text, market_home = await market_handler.render_market(uid)
    market_home_datas = _datas(market_home)
    assert {"market:cat:buy", "market:cat:sell"} <= set(market_home_datas)
    assert not any(data.startswith(("market:buy:", "market:buy_edit:", "market:list:", "market:cancel:"))
                   for data in market_home_datas)
    _text, market_buy = await market_handler.render_market_category(uid, "buy")
    assert any(data.startswith("market:buy_edit:") for data in _datas(market_buy))
    _text, market_sell = await market_handler.render_market_category(uid, "sell")
    assert any(data.startswith("market:list:") for data in _datas(market_sell))

    _text, skills_home = await skills_handler.render_skills(uid)
    skills_home_datas = _datas(skills_home)
    assert {"skills:cat:equipment", "skills:cat:pages"} <= set(skills_home_datas)
    assert not any(data.startswith(("equip:", "eq:", "learn:")) for data in skills_home_datas)
    _text, skills_equipment = await skills_handler.render_skills_category(uid, "equipment")
    assert any(data.startswith("eq:enhance:") for data in _datas(skills_equipment))


def test_action_result_markup_returns_to_section_or_main_menu():
    markup = section_back_markup("↩️ 返回炼制", "nav:craft")

    assert _datas(markup) == ["nav:craft", "nav:menu"]
