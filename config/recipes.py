"""炼丹 / 炼器配方（静态配置，spec §8）。"""
from __future__ import annotations


def _minutes(value: int) -> int:
    return value * 60


RECIPES = {
    "heal_pill": {
        "name": "疗伤丹", "type": "alchemy", "realm": 1, "seconds": _minutes(3),
        "stone": 25, "materials": {"灵草": 3}, "output": {"kind": "item", "key": "疗伤丹", "qty": 1},
        "default": True,
    },
    "stamina_pill": {
        "name": "补灵丹", "type": "alchemy", "realm": 1, "seconds": _minutes(4),
        "stone": 30, "materials": {"灵草": 2, "妖丹": 1},
        "output": {"kind": "item", "key": "补灵丹", "qty": 1}, "default": True,
    },
    "might_pill": {
        "name": "虎力丹", "type": "alchemy", "realm": 1, "seconds": _minutes(5),
        "stone": 35, "materials": {"灵草": 2, "兽皮": 1},
        "output": {"kind": "item", "key": "虎力丹", "qty": 1}, "default": True,
    },
    "focus_pill": {
        "name": "凝神丹", "type": "alchemy", "realm": 1, "seconds": _minutes(5),
        "stone": 35, "materials": {"灵草": 3},
        "output": {"kind": "item", "key": "凝神丹", "qty": 1}, "default": True,
    },
    "foundation_pill": {
        "name": "筑基丹", "type": "alchemy", "realm": 1, "seconds": _minutes(8),
        "stone": 80, "materials": {"灵草": 5, "妖丹": 2},
        "output": {"kind": "item", "key": "筑基丹", "qty": 1}, "default": True,
    },
    "restore_pill": {
        "name": "大还丹", "type": "alchemy", "realm": 2, "seconds": _minutes(12),
        "stone": 100, "materials": {"天材地宝": 1, "妖丹": 2},
        "output": {"kind": "item", "key": "大还丹", "qty": 1}, "default": True,
    },
    "marrow_pill": {
        "name": "洗髓丹", "type": "alchemy", "realm": 2, "seconds": _minutes(15),
        "stone": 120, "materials": {"天材地宝": 1, "妖丹": 3},
        "output": {"kind": "item", "key": "洗髓丹", "qty": 1}, "default": False,
    },
    "forge_sword": {
        "name": "玄铁剑", "type": "forge", "realm": 1, "seconds": _minutes(8),
        "stone": 80, "materials": {"玄铁矿": 5, "兽皮": 2},
        "output": {"kind": "equipment", "key": "玄铁剑"}, "default": True,
    },
    "forge_armor": {
        "name": "青木甲", "type": "forge", "realm": 1, "seconds": _minutes(10),
        "stone": 90, "materials": {"灵草": 4, "兽皮": 5},
        "output": {"kind": "equipment", "key": "青木甲"}, "default": True,
    },
    "forge_accessory": {
        "name": "聚灵佩", "type": "forge", "realm": 2, "seconds": _minutes(18),
        "stone": 120, "materials": {"玄铁矿": 4, "妖丹": 2, "天材地宝": 1},
        "output": {"kind": "equipment", "key": "聚灵佩"}, "default": False,
    },
    "forge_yuanying_blade": {
        "name": "天魔刃", "type": "forge", "realm": 3, "seconds": _minutes(24),
        "stone": 980, "materials": {"雷纹玄铁": 4, "天魔残页": 3, "古战魂晶": 2, "器魂": 4},
        "output": {"kind": "equipment", "key": "天魔刃"}, "default": False,
    },
    "forge_yuanying_armor": {
        "name": "战魂甲", "type": "forge", "realm": 3, "seconds": _minutes(26),
        "stone": 1000, "materials": {"白骨精华": 5, "腐泽妖核": 4, "古战魂晶": 3, "器魂": 5},
        "output": {"kind": "equipment", "key": "战魂甲"}, "default": False,
    },
    "forge_yuanying_accessory": {
        "name": "古战佩", "type": "forge", "realm": 3, "seconds": _minutes(28),
        "stone": 960,
        "materials": {"阴风石": 4, "幽冥草": 4, "劫火残晶": 3, "天魔残页": 2, "器魂": 4},
        "output": {"kind": "equipment", "key": "古战佩"}, "default": False,
    },
    "forge_huashen_sword": {
        "name": "陨星剑", "type": "forge", "realm": 4, "seconds": _minutes(30),
        "stone": 1800, "materials": {"星陨砂": 8, "天外残玉": 2, "器魂": 8},
        "output": {"kind": "equipment", "key": "陨星剑"}, "default": False,
    },
    "forge_huashen_armor": {
        "name": "幽都甲", "type": "forge", "realm": 4, "seconds": _minutes(35),
        "stone": 2000, "materials": {"幽都魂晶": 8, "天外残玉": 2, "器魂": 8},
        "output": {"kind": "equipment", "key": "幽都甲"}, "default": False,
    },
    "forge_huashen_accessory": {
        "name": "太虚佩", "type": "forge", "realm": 4, "seconds": _minutes(40),
        "stone": 2200, "materials": {"星陨砂": 4, "幽都魂晶": 4, "天外残玉": 3, "器魂": 10},
        "output": {"kind": "equipment", "key": "太虚佩"}, "default": False,
    },
    "forge_huashen_banner": {
        "name": "星河幡", "type": "forge", "realm": 4, "seconds": _minutes(32),
        "stone": 2100, "materials": {"星陨砂": 6, "天外残玉": 3, "化神丹残方": 4, "器魂": 8},
        "output": {"kind": "equipment", "key": "星河幡"}, "default": False,
    },
    "forge_huashen_robe": {
        "name": "星陨袍", "type": "forge", "realm": 4, "seconds": _minutes(36),
        "stone": 2200, "materials": {"星陨砂": 5, "幽都魂晶": 5, "天外残玉": 3, "器魂": 9},
        "output": {"kind": "equipment", "key": "星陨袍"}, "default": False,
    },
    "forge_huashen_bell": {
        "name": "幽都铃", "type": "forge", "realm": 4, "seconds": _minutes(38),
        "stone": 2250, "materials": {"幽都魂晶": 6, "天外残玉": 4, "化神丹残方": 4, "器魂": 10},
        "output": {"kind": "equipment", "key": "幽都铃"}, "default": False,
    },
    # 残方→化神丹：打通化神丹获取链（残方此前为死材料）。需图纸（化神丹方）习得，非 NPC 直售。
    "huashen_pill": {
        "name": "化神丹", "type": "alchemy", "realm": 4, "seconds": _minutes(30),
        "stone": 1500, "materials": {"化神丹残方": 6, "妖丹": 4},
        "output": {"kind": "item", "key": "化神丹", "qty": 1}, "default": False,
    },
}

ACCELERATE_STONE_PER_MINUTE = 5


def recipes_for_realm(realm: int):
    return [(key, val) for key, val in RECIPES.items() if realm >= val["realm"]]
