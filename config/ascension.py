"""飞升点与账号级被动（v2 M3）。"""
from __future__ import annotations

PASSIVE_CAP = 5
TRIAL_DAOHANG_COST = 500
TRIAL_POINT_REWARD = 1
TRIAL_UNLOCK_REALM = 4  # spec-v3 §3.8：飞升试炼仍在化神圆满开放。
POINTS_PER_PASSIVE_LEVEL = 1
# 溢出凝点按修为定额换算，并只约束溢出这一来源；试炼、Boss、活动兑换不占额度。
OVERFLOW_CULTIVATION_PER_POINT = 100_000
OVERFLOW_WEEKLY_CAP = 14
# T3.2 四源之三/四：化神世界 Boss 前列按名次发飞升点；活动副本兑换消耗材料换飞升点。
BOSS_RANK_POINTS = [3, 2, 1]           # 第 1/2/3 名的飞升点（仅化神 realm4 Boss）
BOSS_ASCENSION_REALM = 4
EXCHANGE_MATERIAL_COST = 3             # 活动商店：N 个活动材料兑 1 飞升点
EXCHANGE_POINT_REWARD = 1
PASSIVES = {
    "hp_pct": "气血",
    "atk_pct": "攻伐",
    "df_pct": "护体",
    "seclusion_pct": "闭关",
}

TIANMEN_BASE_COST = 100
TIANMEN_CONTRIBUTIONS = (100, 1_000, 10_000)
TIANMEN_MILESTONES = {
    3: {"item": "保命符", "qty": 1},
    6: {"item": "转修令", "qty": 1},
    9: {"item": "天外残玉", "qty": 1},
    12: {"item": "炼虚丹残方", "qty": 1},
}
_TIANMEN_TITLES = [
    (12, "天门将启"),
    (9, "太虚留名"),
    (6, "道痕初成"),
    (3, "玄关有应"),
    (1, "天门初叩"),
]


def passive_name(key: str) -> str:
    return PASSIVES.get(key, key)


def passives_maxed(spent: dict) -> bool:
    """四项飞升被动是否均已圆满。"""
    return all(int(spent.get(key, 0) or 0) >= PASSIVE_CAP for key in PASSIVES)


def tianmen_next_cost(level: int) -> int:
    """从当前天门重数叩问下一重所需飞升点。"""
    return TIANMEN_BASE_COST * (2 ** max(0, int(level or 0)))


def tianmen_title(level: int) -> str:
    """天门重数对应的威望称谓。"""
    level = max(0, int(level or 0))
    for threshold, title in _TIANMEN_TITLES:
        if level >= threshold:
            return title
    return ""


# 飞升尊号：按总阶派生（纯函数，零存储/零迁移）。spec §6.3 T3.5"解锁称号"。
_ASCENSION_TITLES = [
    (5, "渡劫仙尊"),
    (3, "飞升真君"),
    (1, "飞升新秀"),
]


def ascension_title(level: int) -> str:
    """飞升总阶 → 尊号；level 0 返回空串（未解锁）。"""
    level = int(level or 0)
    for threshold, title in _ASCENSION_TITLES:
        if level >= threshold:
            return title
    return ""
