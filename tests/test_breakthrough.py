from config import realms as R
from services.breakthrough import big_success_rate


def test_advance_cost_monotonic_within_realm():
    costs = [R.advance_cost(0, s) for s in range(R.num_stages(0))]
    assert costs == sorted(costs)
    assert all(c > 0 for c in costs)


def test_advance_cost_matches_issue8_progression():
    assert R.advance_cost(0, 0) == 200
    assert R.advance_cost(0, 1) == 240


def test_big_success_rate_clamped():
    assert 0.05 <= big_success_rate(0, 0) <= 0.95
    assert big_success_rate(2, 0) >= 0.05
    assert big_success_rate(0, 999) <= 0.95


def test_root_bone_helps():
    assert big_success_rate(0, root_bone=80) > big_success_rate(0, root_bone=40)


def test_realm_progression_flags():
    last_qi = R.num_stages(0) - 1
    assert R.is_big_breakthrough(0, last_qi)
    assert R.next_stage(0, last_qi) == (1, 0)

    assert not R.is_big_breakthrough(0, 0)
    assert R.next_stage(0, 0) == (0, 1)

    last_yy = R.num_stages(3) - 1
    assert R.next_stage(3, last_yy) == (4, 0)
    assert R.is_big_breakthrough(3, last_yy)

    last_hs = R.num_stages(4) - 1
    assert R.next_stage(4, last_hs) == (5, 0)
    assert R.is_big_breakthrough(4, last_hs)

    last_lx = R.num_stages(5) - 1
    assert R.next_stage(5, last_lx) is None
    assert not R.is_big_breakthrough(5, last_lx)


def test_base_stats_increase_with_stage():
    s0 = R.base_stats(0, 0)
    s_last = R.base_stats(0, R.num_stages(0) - 1)
    assert s_last["hp"] > s0["hp"]
    assert s_last["atk"] >= s0["atk"]
