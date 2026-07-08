"""境界、属性、修为成本 —— 全部静态数值（初版可调）。

防御属性键用 ``df``（避开 Python 关键字 ``def``），全局一致。
大境界索引 0..5 = 炼气 / 筑基 / 金丹 / 元婴 / 化神 / 炼虚。
"""
from __future__ import annotations

REALM_NAMES = ["炼气期", "筑基期", "金丹期", "元婴期", "化神期", "炼虚期"]

_QI_LAYERS = ["一层", "二层", "三层", "四层", "五层", "六层", "七层",
              "八层", "九层", "十层", "十一层", "十二层", "十三层"]
_SUB_STAGES = ["初期", "中期", "后期", "圆满"]

REALM_STAGES = {
    0: _QI_LAYERS,
    1: _SUB_STAGES,
    2: _SUB_STAGES,
    3: _SUB_STAGES,
    4: _SUB_STAGES,
    5: _SUB_STAGES,
}

STAT_KEYS = ("hp", "mp", "atk", "df", "spd", "crit")

# 进入某大境界所需的突破丹与基础成功率；金丹起渡天劫。
BIG_BREAKTHROUGH = {
    1: {"pill": "筑基丹", "base_rate": 0.80, "tribulation": False},
    2: {"pill": "金丹", "base_rate": 0.70, "tribulation": True},
    3: {"pill": "元婴丹", "base_rate": 0.60, "tribulation": True},
    4: {"pill": "化神丹", "base_rate": 0.50, "tribulation": True},
    5: {"pill": "炼虚丹", "base_rate": 0.45, "tribulation": True},
}

_REALM_BASE_COST = {0: 200, 1: 800, 2: 6000, 3: 50000, 4: 450000, 5: 4_000_000}
_STAGE_MULT = 1.20

# 属性锚点：每大境界 (初阶, 圆满)，小阶间线性插值。
_ANCHORS = {
    0: (dict(hp=200, mp=40, atk=24, df=16, spd=14, crit=4),
        dict(hp=500, mp=100, atk=60, df=40, spd=30, crit=10)),
    1: (dict(hp=700, mp=140, atk=85, df=58, spd=42, crit=13),
        dict(hp=1500, mp=250, atk=160, df=110, spd=70, crit=25)),
    2: (dict(hp=2200, mp=320, atk=230, df=160, spd=95, crit=33),
        dict(hp=5000, mp=600, atk=450, df=320, spd=160, crit=60)),
    3: (dict(hp=7000, mp=750, atk=620, df=450, spd=200, crit=72),
        dict(hp=16000, mp=1500, atk=1300, df=950, spd=380, crit=140)),
    4: (dict(hp=24000, mp=2200, atk=1850, df=1350, spd=500, crit=175),
        dict(hp=52000, mp=4200, atk=3800, df=2800, spd=900, crit=280)),
    5: (dict(hp=78000, mp=6300, atk=5600, df=4100, spd=1300, crit=420),
        dict(hp=170000, mp=13500, atk=12000, df=8800, spd=2300, crit=700)),
}

STAMINA_CAP = {0: 100, 1: 120, 2: 150, 3: 200, 4: 240, 5: 280}

# 闭关每小阶目标时长（小时），按大境界配置（#15）。
# 炼气小阶多、放快；金丹/元婴小阶少、放慢，抵消"高境界小阶少→整体推进偏快"。
SECLUSION_STAGE_HOURS = {0: 16, 1: 24, 2: 36, 3: 48, 4: 96, 5: 144}
_DEFAULT_SECLUSION_HOURS = 24


def seclusion_stage_seconds(realm: int) -> int:
    """当前大境界闭关填满一个小阶的目标秒数。"""
    return SECLUSION_STAGE_HOURS.get(realm, _DEFAULT_SECLUSION_HOURS) * 3600


def num_stages(realm: int) -> int:
    return len(REALM_STAGES[realm])


def is_last_stage(realm: int, stage: int) -> bool:
    return stage == num_stages(realm) - 1


def realm_label(realm: int, stage: int) -> str:
    return REALM_NAMES[realm] + "·" + REALM_STAGES[realm][stage]


def advance_cost(realm: int, stage: int) -> int:
    """从 (realm, stage) 推进到下一阶 / 下一大境界所需修为。"""
    return int(_REALM_BASE_COST[realm] * (_STAGE_MULT ** stage))


def base_stats(realm: int, stage: int) -> dict:
    start, full = _ANCHORS[realm]
    n = num_stages(realm)
    t = stage / (n - 1) if n > 1 else 0.0
    return {k: int(start[k] + (full[k] - start[k]) * t) for k in STAT_KEYS}


def next_stage(realm: int, stage: int):
    """推进后的 (realm, stage)；已达当前顶点返回 None。"""
    if not is_last_stage(realm, stage):
        return realm, stage + 1
    if realm + 1 < len(REALM_NAMES):
        return realm + 1, 0
    return None


def is_big_breakthrough(realm: int, stage: int) -> bool:
    """当前是否处于跨大境界的大突破节点（本境界圆满且存在下一大境界）。"""
    return is_last_stage(realm, stage) and realm + 1 < len(REALM_NAMES)
