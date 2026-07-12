"""宗门配置（spec §11）。"""
from __future__ import annotations

CREATE_REALM = 1
CREATE_STONE_COST = 500
TASK_CONTRIBUTION = 10
TASK_STONE_REWARD = 30
TASK_STAMINA_REWARD = 20
LEVEL_UP_COST = 100

SECT_SHOP = {
    "归元心法残页": {"contribution": 20, "qty": 1},
    "烈火诀残页": {"contribution": 20, "qty": 1},
    "回春术残页": {"contribution": 20, "qty": 1},
    "玄铁剑图纸": {"contribution": 35, "qty": 1},
    "洗髓丹丹方": {"contribution": 45, "qty": 1},
    "聚灵佩图纸": {"contribution": 45, "qty": 1},
}


def welfare(level: int) -> dict:
    return {
        "stat_pct": min(0.10, level * 0.02),
        "seclusion_pct": min(0.25, level * 0.05),
        "stamina_bonus": level * 5,
        "offline_extra_hours": level,
        "drop_pct": min(0.15, level * 0.03),
    }


def upgrade_cost(level: int) -> int:
    return max(LEVEL_UP_COST, level * LEVEL_UP_COST)


# 灵石长线 sink（#13）：个人捐灵石换少量贡献（每日封顶）；升级在贡献池外另耗宗主灵石。
DONATE_STONE_PER_CONTRIBUTION = 10
DONATE_DAILY_CONTRIBUTION_CAP = 50
UPGRADE_STONE_COST_PER_LEVEL = 200


def upgrade_stone_cost(level: int) -> int:
    return level * UPGRADE_STONE_COST_PER_LEVEL
