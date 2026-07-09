from __future__ import annotations

from config import realms as R
from config.dungeons import DUNGEONS
from services import shop
from tools import balance_sim as B


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
