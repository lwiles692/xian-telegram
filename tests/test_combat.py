from __future__ import annotations

from config import realms as R
from services import pvp
from services.combat import (
    CombatRules, HARD_ROUND_CAP, MAX_ROUNDS, Combatant, round_limit_label, simulate)
from tools import balance_sim as B


def _mk(name, hp=1000, atk=100, df=50, spd=30, crit=10, mp=100, skills=None, **mods):
    return Combatant(name=name, hp=hp, mp=mp, atk=atk, df=df, spd=spd,
                     crit=crit, skills=skills or ["普攻"], **mods)


def test_deterministic_same_seed():
    r1 = simulate(_mk("甲"), _mk("乙", spd=20), seed=42)
    r2 = simulate(_mk("甲"), _mk("乙", spd=20), seed=42)
    assert r1["log"] == r2["log"]
    assert r1["winner"].name == r2["winner"].name
    assert r1["rounds"] == r2["rounds"]


def test_stronger_wins():
    strong = _mk("强", hp=3000, atk=300, df=120)
    weak = _mk("弱", hp=500, atk=40, df=20)
    assert simulate(strong, weak, seed=1)["winner"].name == "强"


def test_winner_is_input_object():
    a, b = _mk("甲"), _mk("乙")
    assert simulate(a, b, seed=7)["winner"] in (a, b)


def test_rounds_capped_and_resolved():
    a = _mk("甲", hp=100000, atk=1, df=10000)
    b = _mk("乙", hp=100000, atk=1, df=10000, spd=10)
    r = simulate(a, b, seed=3)
    assert r["rounds"] <= MAX_ROUNDS
    assert r["winner"] in (a, b)
    assert r["reason"] == "round_limit"
    assert round_limit_label() in r["log"][-1]


def test_unbounded_combat_runs_past_default_round_limit_to_defeat():
    a = _mk("甲", hp=200, atk=6, df=300, spd=30, crit=0)
    b = _mk("乙", hp=200, atk=6, df=300, spd=10, crit=0)

    r = simulate(a, b, seed=3, max_rounds=None)

    assert r["rounds"] > MAX_ROUNDS
    assert r["winner"] in (a, b)
    assert r["reason"] in ("defeat", "double_down")


def test_unbounded_stalemate_terminates_at_hard_cap():
    # 净治疗 >> 净伤害的僵局：max_rounds=None 本会无限循环并撑爆 log/事件循环。
    # 硬上限必须让它终止，并退回按气血比例判定（避免 OOM）。
    a = _mk("甲", hp=1000, atk=1, df=100000, mp=1000, skills=["回春术", "普攻"])
    b = _mk("乙", hp=1000, atk=1, df=100000, mp=1000, spd=10, skills=["回春术", "普攻"])

    r = simulate(a, b, seed=3, max_rounds=None)

    assert r["rounds"] == HARD_ROUND_CAP
    assert r["reason"] == "round_limit"
    assert r["winner"] in (a, b)
    assert len(r["log"]) < HARD_ROUND_CAP * 6  # log 有界


def test_skill_used_when_affordable():
    # 快剑斩 系数高，强者带技能应能赢且日志含技能名
    a = _mk("剑修", atk=200, skills=["快剑斩"])
    b = _mk("木桩", hp=400, atk=10, df=10)
    r = simulate(a, b, seed=5)
    assert any("快剑斩" in line for line in r["log"])


def test_combat_affixes_lifesteal_reflect_and_initiative():
    slow = _mk("慢剑", hp=1000, atk=240, spd=1, lifesteal_pct=0.5, initiative=100)
    thorn = _mk("反甲", hp=1000, atk=10, spd=80, reflect_pct=0.2)

    r = simulate(slow, thorn, seed=11)

    assert "慢剑" in r["log"][1]
    assert any("汲取气血" in line for line in r["log"])
    assert any("反震" in line for line in r["log"])


def test_pressure_does_not_overturn_fresh_knockout():
    rules = CombatRules(
        pressure_start_round=1,
        pressure_base_pct=0.01,
        pressure_growth_pct=1.0,
        pressure_cap_pct=1.0,
    )
    attacker = _mk(
        "低血剑修", hp=5, max_hp=100, atk=10000, df=0,
        spd=10, initiative=1000, skills=["金钟罩", "快剑斩"])
    defender = _mk("高速败者", hp=20, atk=1, df=0, spd=100, crit=0, skills=["普攻"])

    r = simulate(attacker, defender, seed=1, max_rounds=2, rules=rules)

    assert r["winner"] is attacker
    assert r["reason"] == "defeat"
    assert r["a_hp"] > 0
    assert r["d_hp"] == 0


def test_pvp_duel_ban_preserves_early_healing():
    healer = _mk("药修", hp=500, max_hp=1000, atk=1, df=10000,
                 mp=100, spd=100, crit=0, skills=["回春术"])
    target = _mk("木桩", hp=1000, atk=1, df=10000, mp=0, spd=1, crit=0, skills=["普攻"])

    r = simulate(healer, target, seed=1, max_rounds=1, rules=pvp.PVP_COMBAT_RULES)

    assert any("回复气血 150" in line for line in r["log"])


def _profile_player(name: str, realm: int, stage: int, profile: dict,
                    skills: list[str], **mods) -> Combatant:
    st = B.build_player_stats(realm, stage, profile)
    return Combatant(name=name, hp=st["hp"], mp=st["mp"], atk=st["atk"],
                     df=st["df"], spd=st["spd"], crit=st["crit"],
                     skills=skills, **mods)


def test_pvp_duel_ban_resolves_common_huashen_profiles():
    last = R.num_stages(4) - 1
    profiles = [
        ("化神主线", 4, last, B.HUASHEN_GEARED, {}),
        ("化神分支", 4, last, B.HUASHEN_BRANCH_GEARED, {}),
        ("剑修宗师", 4, last, {**B.HUASHEN_GEARED, "dao_path": "sword",
                              "dao_rank": 4, "dao_refine": 20}, {}),
        ("体修宗师", 4, last, {**B.HUASHEN_GEARED, "dao_path": "body",
                              "dao_rank": 4, "dao_refine": 20}, {}),
        ("极限龟甲", 4, last, {**B.HUASHEN_GEARED,
                              "extra_pct": {"hp": 0.25, "df": 0.25}},
         {"lifesteal_pct": 0.27, "crit_resist": 80, "reflect_pct": 0.15}),
        ("元婴圆满", 3, R.num_stages(3) - 1, B.YUANYING_TREASURE_GEARED, {}),
        ("化神初期", 4, 0, B.HUASHEN_GEARED, {}),
    ]
    skillsets = [
        ("标准", ["快剑斩", "烈火诀", "回春术"]),
        ("攻杀", ["快剑斩", "烈火诀"]),
        ("盾攻", ["快剑斩", "金钟罩", "回春术"]),
        ("普攻", ["普攻"]),
    ]
    timeouts = []
    longest = 0

    for skill_name, skills in skillsets:
        for an, ar, astage, aprofile, amods in profiles:
            for dn, dr, dstage, dprofile, dmods in profiles:
                if abs(ar - dr) > 1:
                    continue
                for seed in range(10):
                    a = _profile_player(an, ar, astage, aprofile, skills, **amods)
                    d = _profile_player(dn, dr, dstage, dprofile, skills, **dmods)
                    res = simulate(
                        a, d, seed=seed, max_rounds=pvp.PVP_MAX_ROUNDS,
                        rules=pvp.PVP_COMBAT_RULES)
                    longest = max(longest, res["rounds"])
                    if res["reason"] == "round_limit":
                        timeouts.append((skill_name, an, dn, seed))

    assert timeouts == []
    assert longest < pvp.PVP_MAX_ROUNDS


def test_pvp_duel_ban_keeps_pure_stall_as_round_limit_edge_case():
    last = R.num_stages(4) - 1
    profile = {**B.HUASHEN_GEARED, "extra_pct": {"hp": 0.25, "df": 0.25}}
    skills = ["回春术", "金钟罩", "定身符"]
    rounds = []
    reasons = []

    for seed in range(10):
        a = _profile_player("龟甲甲", 4, last, profile, skills,
                            lifesteal_pct=0.27, crit_resist=80, reflect_pct=0.15)
        d = _profile_player("龟甲乙", 4, last, profile, skills,
                            lifesteal_pct=0.27, crit_resist=80, reflect_pct=0.15)
        res = simulate(
            a, d, seed=seed, max_rounds=pvp.PVP_MAX_ROUNDS,
            rules=pvp.PVP_COMBAT_RULES)
        rounds.append(res["rounds"])
        reasons.append(res["reason"])

    assert rounds == [pvp.PVP_MAX_ROUNDS] * 10
    assert reasons == ["round_limit"] * 10
