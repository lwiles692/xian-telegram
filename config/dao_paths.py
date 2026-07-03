"""道途配置（v2 M2）。"""
from __future__ import annotations

UNLOCK_REALM = 3

RANK_NAMES = ["入门", "小成", "大成", "圆满", "宗师"]
RANK_UP_COSTS = {
    1: {"daohang": 100, "items": {}},
    2: {"daohang": 300, "items": {"星陨砂": 1}},
    3: {"daohang": 800, "items": {"幽都魂晶": 1}},
    4: {"daohang": 1600, "items": {"天外残玉": 1}, "ascension_points": 1},
}
SWITCH_TOKEN = "转修令"
SWITCH_STONE_COST = 2000
SWITCH_COOLDOWN_SECONDS = 7 * 86400

# 道途淬炼：选定道途后即可花道行深化本道（不 gate 在满阶/宗师后——那需 rank-4 材料，会把
# 恰恰卡住、缺材料上不去的目标人群挡在门外），为高境界囤积的道行提供出口。
# 每层按 REFINE_PER_LEVEL_PCT 只叠加到本道途「未触顶」的那个维度（主攻伐/主生存维已贴 25%
# clamp，加了会被吃掉），仍走既有 BUFF clamp，绝不破天花板。
REFINE_MAX_LEVEL = 20
REFINE_PER_LEVEL_PCT = 0.005
REFINE_COST_BASE = 300     # 淬炼第 L 层（L 从 1 起）花费 = REFINE_COST_BASE * L，递增
# 各道途淬炼强化的维度：选头部空间最大的次级/功能维，避开近顶的主维度。
REFINE_STATS = {
    "sword": "crit_pct",       # atk 近顶 → 强 crit
    "body": "df_pct",          # hp 近顶 → 强 df
    "alchemy": "alchemy_pct",  # mp 近顶 → 强丹术（功能维无战力顶）
    "forge": "forge_pct",      # 强炼器（功能维）
    "talisman": "seclusion_pct",  # 闭关 clamp 60%，头部空间最大 → 直强本命维
}

DAO_PATHS = {
    "sword": {
        "name": "剑修",
        "role": "攻伐与 Boss 伤害",
        "bonuses": [
            {"atk_pct": 0.03, "crit_pct": 0.02},
            {"atk_pct": 0.06, "crit_pct": 0.04},
            {"atk_pct": 0.10, "crit_pct": 0.06},
            {"atk_pct": 0.14, "crit_pct": 0.08},
            {"atk_pct": 0.18, "crit_pct": 0.10},
        ],
    },
    "body": {
        "name": "体修",
        "role": "生存与秘境推进",
        "bonuses": [
            {"hp_pct": 0.03, "df_pct": 0.02},
            {"hp_pct": 0.06, "df_pct": 0.04},
            {"hp_pct": 0.10, "df_pct": 0.06},
            {"hp_pct": 0.14, "df_pct": 0.08},
            {"hp_pct": 0.18, "df_pct": 0.10},
        ],
    },
    "alchemy": {
        "name": "丹修",
        "role": "丹药与突破辅助",
        "bonuses": [
            {"mp_pct": 0.03, "alchemy_pct": 0.02},
            {"mp_pct": 0.06, "alchemy_pct": 0.04},
            {"mp_pct": 0.10, "alchemy_pct": 0.06},
            {"mp_pct": 0.14, "alchemy_pct": 0.08},
            {"mp_pct": 0.18, "alchemy_pct": 0.10},
        ],
    },
    "forge": {
        "name": "器修",
        "role": "法宝与强化",
        "bonuses": [
            {"atk_pct": 0.02, "df_pct": 0.02, "forge_pct": 0.02},
            {"atk_pct": 0.04, "df_pct": 0.04, "forge_pct": 0.04},
            {"atk_pct": 0.07, "df_pct": 0.06, "forge_pct": 0.06},
            {"atk_pct": 0.10, "df_pct": 0.08, "forge_pct": 0.08},
            {"atk_pct": 0.13, "df_pct": 0.10, "forge_pct": 0.10},
        ],
    },
    "talisman": {
        "name": "符阵",
        "role": "闭关与洞府效率",
        "bonuses": [
            {"seclusion_pct": 0.03, "spd_pct": 0.02},
            {"seclusion_pct": 0.06, "spd_pct": 0.04},
            {"seclusion_pct": 0.10, "spd_pct": 0.06},
            {"seclusion_pct": 0.14, "spd_pct": 0.08},
            {"seclusion_pct": 0.18, "spd_pct": 0.10},
        ],
    },
}


def path_name(path_key: str) -> str:
    return DAO_PATHS.get(path_key, {}).get("name", path_key)


def rank_name(rank: int) -> str:
    if 0 <= rank < len(RANK_NAMES):
        return RANK_NAMES[rank]
    return RANK_NAMES[-1]


def refine_cost(level: int) -> int:
    """从 level（已淬炼层数，0 起）升下一层所需道行。"""
    return REFINE_COST_BASE * (int(level) + 1)


def bonuses_for(path_key: str, rank: int, refine_level: int = 0) -> dict:
    path = DAO_PATHS.get(path_key)
    if not path:
        return {}
    idx = max(0, min(int(rank), len(path["bonuses"]) - 1))
    bonuses = dict(path["bonuses"][idx])
    lvl = max(0, min(int(refine_level or 0), REFINE_MAX_LEVEL))
    stat = REFINE_STATS.get(path_key)
    if lvl and stat:
        bonuses[stat] = round(bonuses.get(stat, 0.0) + lvl * REFINE_PER_LEVEL_PCT, 4)
    return bonuses
