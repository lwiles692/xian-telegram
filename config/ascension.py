"""飞升点与账号级被动（v2 M3）。"""
from __future__ import annotations

PASSIVE_CAP = 5
TRIAL_DAOHANG_COST = 500
TRIAL_POINT_REWARD = 1
TRIAL_UNLOCK_REALM = 4  # spec-v3 §3.8：飞升试炼仍在化神圆满开放。
POINTS_PER_PASSIVE_LEVEL = 1
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


def passive_name(key: str) -> str:
    return PASSIVES.get(key, key)


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
