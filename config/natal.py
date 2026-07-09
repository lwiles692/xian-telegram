from __future__ import annotations

"""本命法宝配置（spec-v3 §7.2 / M5）。"""

MIN_REALM = 3
ELIGIBLE_TIERS = frozenset({"宝", "玄"})
MAX_LEVEL = 10
FORGE_PATH_KEY = "forge"

BIND_COSTS = {
    "宝": {"stone": 30_000, "items": {"器魂": 8, "天材地宝": 2}},
    "玄": {"stone": 120_000, "items": {"器魂": 18, "星陨砂": 2, "幽都魂晶": 2, "天外残玉": 1}},
}

FEED_COSTS = {
    2: {"stone": 4_000, "items": {"器魂": 3, "星陨砂": 1}},
    3: {"stone": 7_000, "items": {"器魂": 4, "幽都魂晶": 1}},
    4: {"stone": 11_000, "items": {"器魂": 5, "天外残玉": 1}},
    5: {"stone": 16_000, "items": {"器魂": 6, "雾泽虚砂": 1}},
    6: {"stone": 22_000, "items": {"器魂": 7, "雾泽虚砂": 2}},
    7: {"stone": 30_000, "items": {"器魂": 8, "裂海空髓": 1}},
    8: {"stone": 40_000, "items": {"器魂": 10, "裂海空髓": 2}},
    9: {"stone": 52_000, "items": {"器魂": 12, "混沌残核": 1}},
    10: {"stone": 70_000, "items": {"器魂": 15, "混沌残核": 2}},
}

UNBIND_COSTS = (
    (3, 80_000),
    (6, 160_000),
    (MAX_LEVEL, 300_000),
)

SLOT_BONUS_PER_LEVEL = {
    "weapon": {"atk": 0.006},
    "armor": {"hp": 0.004, "df": 0.004},
    "accessory": {"mp": 0.004, "spd": 0.004},
}


def bind_cost(tier: str) -> dict:
    cost = BIND_COSTS.get(tier, BIND_COSTS["宝"])
    return {"stone": cost["stone"], "items": dict(cost["items"])}


def feed_cost(level: int, forge_path: bool = False) -> dict:
    cost = FEED_COSTS[int(level)]
    stone = int(cost["stone"] * (0.9 if forge_path else 1.0))
    items = dict(cost["items"])
    if forge_path and "器魂" in items:
        items["器魂"] = max(1, int(items["器魂"]) - 1)
    return {"stone": stone, "items": items}


def unbind_cost(level: int) -> int:
    level = max(1, min(int(level or 1), MAX_LEVEL))
    for upper, cost in UNBIND_COSTS:
        if level <= upper:
            return cost
    return UNBIND_COSTS[-1][1]


def slot_bonus(slot: str, level: int) -> dict[str, float]:
    base = SLOT_BONUS_PER_LEVEL.get(slot.split(":", 1)[0], {})
    lvl = max(0, min(int(level or 0), MAX_LEVEL))
    return {key: round(val * lvl, 4) for key, val in base.items()}
