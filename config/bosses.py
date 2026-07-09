from __future__ import annotations

"""世界 Boss 配置（spec §5.3；分档重做见 #14）。

设计口径（消除旧版 total_hp 与战斗假人尺度不一致的问题）：

- ``combat``：战斗假人，仅用于按各档玩家属性*量出每次挑战的 chip 伤害*；
  其 ``hp`` 故意设得极高，确保单次挑战打不死、伤害反映真实 DPS。
- ``total_hp``：群共享血池，由"目标群规模 × 目标人均挑战次数 × 该档典型(后期)
  玩家单次伤害"反推而来（约 36 次挑战量级，落在 10-20 人 × 2-4 次区间内）。
"""

WORLD_BOSSES = {
    "zhuji": {
        "name": "噬血妖王", "realm": 1, "total_hp": 50000, "duration": 2 * 3600,
        "stamina": 12, "stone_pool": 1500,
        "drops": {"妖丹": 12, "玄铁矿": 9, "金丹": 3},
        "combat": {
            "name": "噬血妖王", "hp": 500000, "mp": 2000, "atk": 210,
            "df": 170, "spd": 70, "crit": 25, "skills": ["普攻", "烈火诀", "金钟罩"],
        },
    },
    "jindan": {
        "name": "焚天妖皇", "realm": 2, "total_hp": 150000, "duration": 2 * 3600,
        "stamina": 13, "stone_pool": 4000,
        "drops": {"妖丹": 15, "天材地宝": 4, "元婴丹": 2},
        "combat": {
            "name": "焚天妖皇", "hp": 2000000, "mp": 2000, "atk": 560,
            "df": 470, "spd": 130, "crit": 50, "skills": ["普攻", "烈火诀", "金钟罩"],
        },
    },
    "yuanying": {
        "name": "噬世妖圣", "realm": 3, "total_hp": 250000, "duration": 2 * 3600,
        "stamina": 15, "stone_pool": 9000,
        "drops": {"天材地宝": 6, "元婴丹": 4, "聚灵佩图纸": 2},
        "combat": {
            "name": "噬世妖圣", "hp": 8000000, "mp": 2000, "atk": 1500,
            "df": 1250, "spd": 280, "crit": 110, "skills": ["普攻", "烈火诀", "金钟罩"],
        },
    },
    "huashen": {
        "name": "天外魔尊", "realm": 4, "total_hp": 900000, "duration": 2 * 3600,
        "stamina": 18, "stone_pool": 18000,
        "drops": {"星陨砂": 10, "幽都魂晶": 8, "天外残玉": 6, "转修令": 2, "炼虚丹残方": 3},
        "combat": {
            "name": "天外魔尊", "hp": 30000000, "mp": 5000, "atk": 4200,
            "df": 3300, "spd": 780, "crit": 260, "skills": ["普攻", "快剑斩", "烈火诀", "金钟罩"],
        },
    },
    "lianxu": {
        "name": "吞虚魔蟒", "realm": 5, "total_hp": 1200000, "duration": 2 * 3600,
        "stamina": 20, "stone_pool": 28000,
        "drops": {
            "雾泽虚砂": 6,
            "裂海空髓": 5,
            "混沌残核": 4,
            "炼虚丹残方": 4,
            "炼虚装备图纸残页": 4,
            "天外残玉": 3,
            "转修令": 2,
        },
        "combat": {
            "name": "吞虚魔蟒", "hp": 100000000, "mp": 8000, "atk": 9000,
            "df": 7000, "spd": 1700, "crit": 520,
            "skills": ["普攻", "快剑斩", "烈火诀", "金钟罩"],
        },
    },
}

# Boss 血量按本群已知修仙者人数缩放；达到该人数后使用配置满血。
WORLD_BOSS_FULL_HP_CULTIVATORS = 10

# 默认档（无历史信息时用筑基入门档）。
DEFAULT_BOSS = "zhuji"
LEGACY_BOSS_ALIASES = {"ancient_dragon": "zhuji"}

_REALM_TIER = {0: "zhuji", 1: "zhuji", 2: "jindan", 3: "yuanying", 4: "huashen", 5: "lianxu"}


def canonical_boss_key(key: str) -> str:
    """兼容旧库中的 Boss key；未知 key 降级到默认档。"""
    if key in WORLD_BOSSES:
        return key
    return LEGACY_BOSS_ALIASES.get(key, DEFAULT_BOSS)


def boss_key_for_realm(realm: int) -> str:
    """按境界选择 Boss 档位（#14）。"""
    return _REALM_TIER.get(realm, DEFAULT_BOSS)
