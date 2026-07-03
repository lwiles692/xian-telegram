"""物品定义（静态）。type: equipment/material/pill/page/recipe。"""
from __future__ import annotations

ITEMS = {
    "新手剑": {"name": "新手木剑", "type": "equipment", "slot": "weapon",
             "tier": "凡", "bonus": {"atk": 5}},
    "玄铁剑": {"name": "玄铁剑", "type": "equipment", "slot": "weapon",
             "tier": "灵", "bonus": {"atk": 38, "crit": 4}},
    "青木甲": {"name": "青木甲", "type": "equipment", "slot": "armor",
             "tier": "灵", "bonus": {"hp": 160, "df": 28}, "tribulation_shield": 60},
    "聚灵佩": {"name": "聚灵佩", "type": "equipment", "slot": "accessory",
             "tier": "宝", "bonus": {"mp": 80, "spd": 10}, "breakthrough_rate": 0.03},
    "灵草":   {"name": "灵草",     "type": "material", "sell": 4},
    "玄铁矿": {"name": "玄铁矿",   "type": "material", "sell": 8},
    "兽皮":   {"name": "妖兽皮",   "type": "material", "sell": 5},
    "妖丹":   {"name": "妖丹",     "type": "material", "sell": 18},
    "天材地宝": {"name": "天材地宝", "type": "material", "sell": 80},
    "器魂":   {"name": "器魂",     "type": "material", "sell": 6},
    # 困难图独占材料（#20）：留作后续炼丹/炼器/突破扩展，卖价偏低以免成为灵石 faucet。
    "阴风石": {"name": "阴风石",   "type": "material", "sell": 8},
    "幽冥草": {"name": "幽冥草",   "type": "material", "sell": 8},
    "白骨精华": {"name": "白骨精华", "type": "material", "sell": 20},
    "腐泽妖核": {"name": "腐泽妖核", "type": "material", "sell": 20},
    "雷纹玄铁": {"name": "雷纹玄铁", "type": "material", "sell": 50},
    "劫火残晶": {"name": "劫火残晶", "type": "material", "sell": 50},
    "天魔残页": {"name": "天魔残页", "type": "material", "sell": 60},
    "古战魂晶": {"name": "古战魂晶", "type": "material", "sell": 60},
    "疗伤丹": {"name": "疗伤丹",   "type": "pill", "sell": 20},
    "补灵丹": {"name": "补灵丹",   "type": "pill", "sell": 20},
    "大还丹": {"name": "大还丹",   "type": "pill", "sell": 55},
    "虎力丹": {"name": "虎力丹",   "type": "pill", "sell": 35, "use": "buff",
             "buff": {"atk_pct": 0.10}, "duration": 3600},
    "凝神丹": {"name": "凝神丹",   "type": "pill", "sell": 35, "use": "buff",
             "buff": {"seclusion_pct": 0.20}, "duration": 3600},
    "洗髓丹": {"name": "洗髓丹",   "type": "pill", "sell": 120},
    "筑基丹": {"name": "筑基丹",   "type": "pill", "sell": 60},
    "金丹":   {"name": "金丹",     "type": "pill", "sell": 180},
    "元婴丹": {"name": "元婴丹",   "type": "pill", "sell": 500},
    "化神丹": {"name": "化神丹",   "type": "pill", "sell": 700},
    "化神丹残方": {"name": "化神丹残方", "type": "material", "sell": 90},
    "星陨砂": {"name": "星陨砂", "type": "material", "sell": 85},
    "幽都魂晶": {"name": "幽都魂晶", "type": "material", "sell": 95},
    "天外残玉": {"name": "天外残玉", "type": "material", "sell": 110},
    "转修令": {"name": "转修令", "type": "material", "sell": 0},
    "保命符": {"name": "保命符", "type": "pill", "sell": 0, "use": "buff",
             "buff": {"df_pct": 0.20, "hp_pct": 0.10}, "duration": 3600},
    "天魔令": {"name": "天魔令", "type": "material", "sell": 0},
    "丹霞玉": {"name": "丹霞玉", "type": "material", "sell": 0},
    "剑冢铁": {"name": "剑冢铁", "type": "material", "sell": 0},
    "天魔刃": {"name": "天魔刃", "type": "equipment", "slot": "weapon",
             "tier": "宝", "bonus": {"atk": 85, "crit": 7}},
    "战魂甲": {"name": "战魂甲", "type": "equipment", "slot": "armor",
             "tier": "宝", "bonus": {"hp": 360, "df": 60}, "tribulation_shield": 90},
    "古战佩": {"name": "古战佩", "type": "equipment", "slot": "accessory",
             "tier": "宝", "bonus": {"mp": 115, "spd": 15}, "breakthrough_rate": 0.035},
    "陨星剑": {"name": "陨星剑", "type": "equipment", "slot": "weapon",
             "tier": "玄", "bonus": {"atk": 420, "crit": 28}},
    "幽都甲": {"name": "幽都甲", "type": "equipment", "slot": "armor",
             "tier": "玄", "bonus": {"hp": 1800, "df": 320}, "tribulation_shield": 220},
    "太虚佩": {"name": "太虚佩", "type": "equipment", "slot": "accessory",
             "tier": "玄", "bonus": {"mp": 480, "spd": 70}, "breakthrough_rate": 0.04},
    "星河幡": {"name": "星河幡", "type": "equipment", "slot": "weapon",
             "tier": "玄", "bonus": {"atk": 340, "mp": 160, "crit": 30}},
    "星陨袍": {"name": "星陨袍", "type": "equipment", "slot": "armor",
             "tier": "玄", "bonus": {"hp": 1450, "df": 250, "spd": 35},
             "tribulation_shield": 190},
    "幽都铃": {"name": "幽都铃", "type": "equipment", "slot": "accessory",
             "tier": "玄", "bonus": {"mp": 540, "spd": 50}, "breakthrough_rate": 0.035},
    "化神丹方": {"name": "化神丹方", "type": "recipe", "recipe": "huashen_pill"},
    "天魔刃图纸": {"name": "天魔刃图纸", "type": "recipe", "recipe": "forge_yuanying_blade"},
    "战魂甲图纸": {"name": "战魂甲图纸", "type": "recipe", "recipe": "forge_yuanying_armor"},
    "古战佩图纸": {"name": "古战佩图纸", "type": "recipe", "recipe": "forge_yuanying_accessory"},
    "陨星剑图纸": {"name": "陨星剑图纸", "type": "recipe", "recipe": "forge_huashen_sword"},
    "幽都甲图纸": {"name": "幽都甲图纸", "type": "recipe", "recipe": "forge_huashen_armor"},
    "太虚佩图纸": {"name": "太虚佩图纸", "type": "recipe", "recipe": "forge_huashen_accessory"},
    "星河幡图纸": {"name": "星河幡图纸", "type": "recipe", "recipe": "forge_huashen_banner"},
    "星陨袍图纸": {"name": "星陨袍图纸", "type": "recipe", "recipe": "forge_huashen_robe"},
    "幽都铃图纸": {"name": "幽都铃图纸", "type": "recipe", "recipe": "forge_huashen_bell"},
    "归元心法残页": {"name": "归元心法残页", "type": "page", "skill": "归元心法", "need": 3},
    "烈火诀残页": {"name": "烈火诀残页", "type": "page", "skill": "烈火诀", "need": 3},
    "回春术残页": {"name": "回春术残页", "type": "page", "skill": "回春术", "need": 3},
    "洗髓丹丹方": {"name": "洗髓丹丹方", "type": "recipe", "recipe": "marrow_pill"},
    "玄铁剑图纸": {"name": "玄铁剑图纸", "type": "recipe", "recipe": "forge_sword"},
    "青木甲图纸": {"name": "青木甲图纸", "type": "recipe", "recipe": "forge_armor"},
    "聚灵佩图纸": {"name": "聚灵佩图纸", "type": "recipe", "recipe": "forge_accessory"},
}


# 禁止玩家坊市交易的物品（spec §3.4 化神丹不直售；§7.1/T5.4 转修令/保命符默认绑定）。
# 掉落即以 bound=0 进包，但这些关键材料不得经坊市绕过 NPC 直售 / 转修成本 / 绑定语义。
NO_TRADE = frozenset({"转修令", "化神丹", "保命符"})


def is_tradable(key: str) -> bool:
    return key not in NO_TRADE


def item_name(key: str) -> str:
    it = ITEMS.get(key)
    return it["name"] if it else key


def weapon_bonus(key: str) -> dict:
    it = ITEMS.get(key)
    if it and it.get("type") == "equipment":
        return dict(it.get("bonus", {}))
    return {}


def is_equipment(key: str) -> bool:
    return ITEMS.get(key, {}).get("type") == "equipment"


def equipment_slot(key: str) -> str:
    return ITEMS.get(key, {}).get("slot", "")


def sell_price(key: str) -> int:
    return int(ITEMS.get(key, {}).get("sell", 0))


def is_usable(key: str) -> bool:
    item = ITEMS.get(key, {})
    return (
        key in {"疗伤丹", "补灵丹", "大还丹", "洗髓丹", "天材地宝"}
        or item.get("use") == "buff"
        or item.get("type") == "recipe"
    )
