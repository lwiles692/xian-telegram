from __future__ import annotations

from config import bonds as BONDS
from config.items import ITEMS, is_tradable
from config.recipes import RECIPES


def test_同心结配置为绑定结契信物并有炼器来源():
    assert BONDS.PARTNER_MIN_REALM == 2
    assert BONDS.PARTNER_KNOT_ITEM == "同心结"
    assert BONDS.PARTNER_DISSOLVE_STONE_COST == 50_000

    item = ITEMS[BONDS.PARTNER_KNOT_ITEM]
    assert item["type"] == "material"
    assert item["sell"] == 0
    assert not is_tradable(BONDS.PARTNER_KNOT_ITEM)

    recipe = RECIPES["partner_knot"]
    assert recipe["name"] == BONDS.PARTNER_KNOT_ITEM
    assert recipe["type"] == "forge"
    assert recipe["realm"] == BONDS.PARTNER_MIN_REALM
    assert recipe["default"] is True
    assert recipe["output"] == {
        "kind": "item",
        "key": BONDS.PARTNER_KNOT_ITEM,
        "qty": 1,
        "bound": 1,
    }
    assert set(recipe["materials"]) <= set(ITEMS)


def test_道侣互赠白名单只含丹药材料并固定红线():
    assert BONDS.PARTNER_DAILY_GIFT_QTY == 1
    assert BONDS.PARTNER_DAILY_GIFT_WHITELIST

    for key in BONDS.PARTNER_DAILY_GIFT_WHITELIST:
        assert key in ITEMS
        assert ITEMS[key]["type"] in {"pill", "material"}
        assert BONDS.is_partner_gift_allowed(key)

    for key in {"同心结", "转修令", "保命符", "化神丹", "炼虚丹", "元婴丹", "玄铁剑"}:
        assert not BONDS.is_partner_gift_allowed(key)
