from __future__ import annotations

from config import maps as M
from config import realms as R


def _weight(drops, key):
    return next((w for k, w, *_ in drops if k == key), 0)


def test_huashen_pill_drop_is_two_thirds_of_yuanying():
    """化神丹掉率 = 元婴丹的 2/3（天魔古原同图对比：元婴丹 6% → 化神丹 4%）。"""
    drops = M.MAPS["天魔古原"]["drops"]
    yuanying = _weight(drops, "元婴丹")
    huashen = _weight(drops, "化神丹")
    assert yuanying == 6
    assert huashen == round(yuanying * 2 / 3)  # 4
    # 天外古墟（化神难图）同步为 4%。
    assert _weight(M.MAPS["天外古墟"]["drops"], "化神丹") == 4


def test_realm4_config_complete():
    assert len(R.REALM_NAMES) == 6
    assert R.REALM_STAGES[4] == R.REALM_STAGES[3]
    assert R.STAMINA_CAP[4] == 240
    assert R.SECLUSION_STAGE_HOURS[4] == 96
    assert R._REALM_BASE_COST[4] == 450000
    assert 4 in R._ANCHORS
    assert R.BIG_BREAKTHROUGH[4] == {"pill": "化神丹", "base_rate": 0.50, "tribulation": True}


def test_realm5_config_complete():
    assert R.REALM_NAMES[5] == "炼虚期"
    assert R.REALM_STAGES[5] == R.REALM_STAGES[4]
    assert R.STAMINA_CAP[5] == 280
    assert R.SECLUSION_STAGE_HOURS[5] == 720
    assert R._REALM_BASE_COST[5] == 4_000_000
    assert R._ANCHORS[5] == (
        dict(hp=78000, mp=6300, atk=5600, df=4100, spd=1300, crit=420),
        dict(hp=170000, mp=13500, atk=12000, df=8800, spd=2300, crit=700),
    )
    assert R.BIG_BREAKTHROUGH[5] == {"pill": "炼虚丹", "base_rate": 0.45, "tribulation": True}


def test_realm4_progression_and_stats():
    assert R.next_stage(3, 3) == (4, 0)
    assert R.is_big_breakthrough(3, 3) is True
    assert R.next_stage(4, 3) == (5, 0)
    assert R.is_big_breakthrough(4, 3) is True
    assert R.base_stats(4, 0)["hp"] == 24000
    assert R.base_stats(4, 3)["hp"] == 52000


def test_realm5_progression_and_stats():
    assert R.next_stage(5, 3) is None
    assert R.is_big_breakthrough(5, 3) is False
    assert R.base_stats(5, 0)["hp"] == 78000
    assert R.base_stats(5, 3)["hp"] == 170000
