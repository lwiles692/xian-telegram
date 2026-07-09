from __future__ import annotations

"""数值平衡回归测试(#15)。

基于 tools.balance_sim(纯函数、固定 seed → 确定值)。覆盖入门/中期/圆满
三个阶段的地图、秘境胜率,以及闭关按境界配时长。

设计说明:战斗引擎含 15% 最大生命的治疗 + 1.8x 爆发技,单场胜负近乎二值
(非连续概率)。因此"普通小怪可刷、Boss 作为成长门槛"用如下稳定口径表达:
小怪单场必胜(可参与新图)、连战可刷;秘境入门能推进半数以上层数,
个别档位可接近通关;Boss 入门打不动、本境界中后期能过。
"""
from config import buffs as BUFFS
from config import dao_paths as DAO
from config import realms as R
from tools import balance_sim as B

MAP_OF = {1: "妖兽森林", 2: "万妖岭", 3: "上古战场", 4: "星陨海", 5: "太初雾泽"}   # 各境界「易」档
DGN_OF = {1: "xuanming", 2: "qingyun", 3: "tianxu"}

# 各大境界 (易, 中, 难) 三档地图(#20)。
TIERS = {
    0: ("后山", "碧萝竹海", "阴风古洞"),
    1: ("妖兽森林", "赤霞岩谷", "枯骨沼泽"),
    2: ("万妖岭", "碧毒蛟潭", "九霄雷泽"),
    3: ("上古战场", "归墟裂谷", "天魔古原"),
    4: ("星陨海", "幽都裂隙", "天外古墟"),
    5: ("太初雾泽", "虚空裂海", "混沌古狱"),
}


# ---- 闭关按境界配时长(#15-1) ----

def test_seclusion_stage_seconds_increases_with_realm():
    secs = [R.seclusion_stage_seconds(r) for r in range(len(R.REALM_NAMES))]
    assert secs == [16 * 3600, 24 * 3600, 36 * 3600, 48 * 3600, 96 * 3600, 720 * 3600]
    assert secs == sorted(secs)  # 越高境界每小阶越慢,抵消"小阶少→偏快"


def test_alchemy_craft_seconds_make_acceleration_meaningful():
    """丹药炼制进入分钟级阶梯,让灵石加速不再被 1 分钟封顶吞掉。"""
    from config.recipes import RECIPES
    from services.dungeon import DUNGEON_DURATION_SECONDS
    from services import crafting

    expected = {
        "heal_pill": 3 * 60,
        "stamina_pill": 4 * 60,
        "might_pill": 5 * 60,
        "focus_pill": 5 * 60,
        "foundation_pill": 8 * 60,
        "restore_pill": 12 * 60,
        "marrow_pill": 15 * 60,
    }
    full_accelerate_costs = {key: crafting.accelerate_cost(seconds) for key, seconds in expected.items()}

    assert {key: RECIPES[key]["seconds"] for key in expected} == expected
    assert full_accelerate_costs == {
        "heal_pill": 15,
        "stamina_pill": 20,
        "might_pill": 25,
        "focus_pill": 25,
        "foundation_pill": 40,
        "restore_pill": 60,
        "marrow_pill": 75,
    }
    assert max(expected.values()) < DUNGEON_DURATION_SECONDS


def test_forge_craft_seconds_make_acceleration_meaningful():
    """炼器产出是长线装备来源,时长略重于同阶常用丹药。"""
    from config.recipes import RECIPES
    from services.dungeon import DUNGEON_DURATION_SECONDS
    from services import crafting

    expected = {
        "forge_sword": 8 * 60,
        "forge_armor": 10 * 60,
        "forge_accessory": 18 * 60,
    }
    full_accelerate_costs = {key: crafting.accelerate_cost(seconds) for key, seconds in expected.items()}

    assert {key: RECIPES[key]["seconds"] for key in expected} == expected
    assert full_accelerate_costs == {
        "forge_sword": 40,
        "forge_armor": 50,
        "forge_accessory": 90,
    }
    assert max(expected.values()) < DUNGEON_DURATION_SECONDS


# ---- 刚突破即可参与新图普通内容(#15-2/3,核心验收) ----

def test_entry_small_mobs_are_farmable():
    for r in (1, 2, 3, 4, 5):
        mob, _ = B.map_winrates(r, 0, MAP_OF[r])
        assert mob >= 0.99, f"r{r} 刚解锁小怪单场胜率过低: {mob:.2f}"
        run = B.map_run_winrate(r, 0, MAP_OF[r])
        assert run >= 0.65, f"r{r} 刚解锁小怪连战胜率过低(刷不动): {run:.2f}"


def test_full_realm_small_mobs_trivial():
    for r in (1, 2, 3, 4, 5):
        last = R.num_stages(r) - 1
        assert B.map_run_winrate(r, last, MAP_OF[r]) >= 0.98


# ---- 地图随机 Boss 作为成长门槛(#15-2) ----

def test_map_boss_is_a_gate():
    for r in (1, 2, 3, 4):
        last = R.num_stages(r) - 1
        entry = B.winrate(r, 0, _boss(r))
        full = B.winrate(r, last, _boss(r))
        assert entry <= 0.35, f"r{r} 刚解锁 Boss 太易({entry:.2f}),失去门槛意义"
        assert full >= 0.85, f"r{r} 圆满仍打不过 Boss({full:.2f})"


def test_map_boss_beatable_by_mid_realm():
    # 至少在本境界中期(stage1)起能稳定击杀随机 Boss。
    for r in (1, 2, 3, 4):
        assert B.winrate(r, 1, _boss(r)) >= 0.85


# ---- 秘境入门可过半数层、圆满稳定通关(#15-2) ----

def test_dungeon_entry_clear_fraction_in_band():
    for r in (1, 2, 3):
        frac = B.dungeon_clear_fraction(r, 0, DGN_OF[r])
        assert 0.45 <= frac <= 0.95, f"r{r} 秘境入门通关层比例越界: {frac:.2f}"


def test_dungeon_full_realm_clears():
    for r in (1, 2, 3):
        last = R.num_stages(r) - 1
        assert B.dungeon_clear_fraction(r, last, DGN_OF[r]) >= 0.95


# ---- 世界 Boss 分档:击杀所需挑战次数落在 10-20 人 × 2-4 次区间(#14) ----

def test_world_boss_tiers_killable_in_target_range():
    from config.bosses import WORLD_BOSSES
    for key, cfg in WORLD_BOSSES.items():
        r = cfg["realm"]
        typ = min(2, R.num_stages(r) - 1)        # 典型参与者=后期
        n_typ = B.world_boss_kill_challenges(key, r, typ)
        assert 20 <= n_typ <= 80, f"{key} 后期击杀需 {n_typ:.0f} 次,超出 10-20人x2-4次区间"


def test_world_boss_total_hp_scaled_not_one_shot():
    # total_hp 与战斗假人尺度统一后,圆满玩家也无法一两次清空血池(否则失去群体意义)。
    from config.bosses import WORLD_BOSSES
    for key, cfg in WORLD_BOSSES.items():
        r = cfg["realm"]
        last = R.num_stages(r) - 1
        assert B.world_boss_kill_challenges(key, r, last) >= 8


# ---- 历练地图扩展:每境界 3 档 + 难度/收益梯度(#20) ----

def test_each_realm_has_three_difficulty_maps():
    from config.maps import maps_at_realm
    for r in sorted(TIERS):
        assert [m["difficulty"] for _, m in maps_at_realm(r)] == ["易", "中", "难"]


def test_difficulty_gradient_on_cost_and_reward():
    from config.maps import MAPS
    for easy, mid, hard in TIERS.values():
        e, m, h = MAPS[easy], MAPS[mid], MAPS[hard]
        assert e["stamina"] < m["stamina"] < h["stamina"]            # 精力梯度
        assert e["boss_rate"] <= m["boss_rate"] <= h["boss_rate"]    # 妖王率梯度
        assert e["cult"] < m["cult"] < h["cult"]                     # 修为梯度
        es, ms, hs = (sum(MAPS[k]["stone"]) / 2 for k in (easy, mid, hard))
        assert es < ms < hs                                          # 灵石梯度


def test_hard_maps_have_exclusive_drops():
    from config.maps import MAPS
    for easy, _mid, hard in TIERS.values():
        easy_keys = {d[0] for d in MAPS[easy]["drops"]}
        hard_only = {d[0] for d in MAPS[hard]["drops"]} - easy_keys
        assert hard_only, f"{hard} 缺少独占掉落"


def test_hard_maps_riskier_than_easy_at_entry():
    # 同境界刚解锁时,难图连战胜率应明显低于易图(高风险)。
    for r in (1, 2, 3, 4, 5):
        easy, _mid, hard = TIERS[r]
        assert B.map_run_winrate(r, 0, hard) < B.map_run_winrate(r, 0, easy)


def test_yuanying_mid_mobs_do_not_depend_on_round_limit():
    """元婴中期刷普通怪应主要靠击杀结算,而不是反复拖到 30 回合判定。"""
    from config.maps import MAPS
    from services.combat import simulate

    for map_key in TIERS[3]:
        for mob in MAPS[map_key]["mobs"]:
            timeouts = 0
            for seed in range(80):
                res = simulate(B.player(3, 1), B._mob(mob), seed=seed)
                timeouts += res["reason"] == "round_limit"
            assert timeouts == 0, f"{mob['name']} 仍有 {timeouts}/80 场拖到回合上限"


# ---- 经济:买精力不能成为刷钱燃料(#16) ----

def test_buy_stamina_costlier_than_best_content_yield():
    """首买精力的单位成本须高于该境界最佳内容的灵石/精力产出,
    使"买精力→刷最佳内容"平均净收益为负(不能稳定套利)。"""
    from services import shop
    for r in range(len(R.REALM_NAMES)):
        cost = shop.first_buy_cost_per_stamina(r)
        yield_per = B.best_content_stone_per_stamina(r)
        assert cost > yield_per, (
            f"r{r} 首买 {cost:.1f} 灵石/精力 未高于最佳产出 {yield_per:.1f}，仍可套利")


def test_yuanying_full_buff_cannot_farm_huashen_mid_hard_bosses():
    """spec §3.2 红线：元婴圆满新装满 buff（推到 §6.3 合算上限）仍不得稳定刷化神中/难 Boss。

    M2 道途 / 飞升被动调参后回归此断言，确保化神门槛未被回溯打穿。
    """
    from config.maps import MAPS
    last = R.num_stages(3) - 1
    for map_key in (TIERS[4][1], TIERS[4][2]):   # 幽都裂隙(中) / 天外古墟(难)
        boss = MAPS[map_key]["boss"]
        wr = B.winrate(3, last, boss, profile=B.YUANYING_FULL_BUFF, n=200)
        assert wr < 0.05, f"{map_key} Boss 被元婴满 buff 刷穿：胜率 {wr:.2%}"


def test_huashen_full_buff_profiles_include_m0_sources():
    """spec-v3 M0 T0.2：化神满 buff 档必须含满道途、满淬炼、飞升被动。"""
    for profile, path_key in (
            (B.HUASHEN_FULL_BUFF_ATK, "sword"),
            (B.HUASHEN_FULL_BUFF_SURV, "body"),
    ):
        assert profile["dao_path"] == path_key
        assert profile["dao_rank"] == len(DAO.RANK_NAMES) - 1
        assert profile["dao_refine"] == DAO.REFINE_MAX_LEVEL
        assert B.ascension_passive_bonuses(profile) == {
            "hp_pct": 0.05,
            "atk_pct": 0.05,
            "df_pct": 0.05,
            "seclusion_pct": 0.05,
        }
    assert B.seclusion_efficiency(B.HUASHEN_FULL_BUFF_SURV) > 1.0


def test_huashen_full_buff_profiles_reach_clamp_ceiling():
    """spec-v3 M0 T0.2：攻击/生存极端档推到全局百分比合算上限。"""
    last = R.num_stages(4) - 1
    atk = B.build_player_stats(4, last, B.HUASHEN_FULL_BUFF_ATK)
    surv = B.build_player_stats(4, last, B.HUASHEN_FULL_BUFF_SURV)
    atk_cap = B.build_player_stats(
        4, last,
        {**B.HUASHEN_GEARED, "extra_pct": {
            "atk": BUFFS.ATTACK_PCT_CAP * 2,
            "crit": BUFFS.ATTACK_PCT_CAP * 2,
        }})
    surv_cap = B.build_player_stats(
        4, last,
        {**B.HUASHEN_GEARED, "extra_pct": {
            "hp": BUFFS.SURVIVAL_PCT_CAP * 2,
            "df": BUFFS.SURVIVAL_PCT_CAP * 2,
        }})

    assert atk["atk"] == atk_cap["atk"]
    assert atk["crit"] == atk_cap["crit"]
    assert surv["hp"] == surv_cap["hp"]
    assert surv["df"] == surv_cap["df"]
    assert B.boss_damage_per_challenge(4, 2, "huashen", profile=B.HUASHEN_FULL_BUFF_ATK, n=80) > (
        B.boss_damage_per_challenge(4, 2, "huashen", profile=B.HUASHEN_FULL_BUFF_SURV, n=80))
    assert surv["hp"] > atk["hp"]
    assert surv["df"] > atk["df"]


def test_yuanying_treasure_gear_fills_mid_map_gap_without_entry_boss_break():
    """#65：元婴宝阶新装应补中档体验，但不能让刚入元婴越过 Boss 门槛。"""
    from config.maps import MAPS

    legacy_run = B.map_run_winrate(3, 0, "归墟裂谷", profile=B.YUANYING_LEGACY_GEARED, n=200)
    treasure_run = B.map_run_winrate(3, 0, "归墟裂谷", profile=B.YUANYING_TREASURE_GEARED, n=200)
    entry_boss = B.winrate(3, 0, MAPS["归墟裂谷"]["boss"], profile=B.YUANYING_TREASURE_GEARED, n=200)

    assert treasure_run >= legacy_run + 0.20
    assert 0.75 <= treasure_run <= 0.95
    assert entry_boss <= 0.05


def test_yuanying_treasure_gear_does_not_turn_hard_boss_into_midgame_farm():
    """#65：中期可挑战归墟 Boss，但天魔古原 Boss 仍是后续成长门槛。"""
    from config.maps import MAPS

    legacy_mid = B.winrate(3, 1, MAPS["归墟裂谷"]["boss"], profile=B.YUANYING_LEGACY_GEARED, n=200)
    treasure_mid = B.winrate(3, 1, MAPS["归墟裂谷"]["boss"], profile=B.YUANYING_TREASURE_GEARED, n=200)
    hard_mid = B.winrate(3, 1, MAPS["天魔古原"]["boss"], profile=B.YUANYING_TREASURE_GEARED, n=200)

    assert legacy_mid <= 0.15
    assert 0.65 <= treasure_mid <= 0.90
    assert hard_mid <= 0.05


def test_huashen_branch_gear_is_sidegrade_not_taixu_replacement():
    """#65：化神分支偏法力/速度，太虚天门推进不得压过主线三件。"""
    main_entry = B.dungeon_clear_fraction(4, 0, "taixu", profile=B.HUASHEN_GEARED, n=120)
    branch_entry = B.dungeon_clear_fraction(4, 0, "taixu", profile=B.HUASHEN_BRANCH_GEARED, n=120)
    branch_full = B.dungeon_clear_fraction(
        4, R.num_stages(4) - 1, "taixu", profile=B.HUASHEN_BRANCH_GEARED, n=120)

    assert 0.20 <= branch_entry <= main_entry - 0.15
    assert branch_full >= 0.95


def test_huashen_branch_world_boss_stays_in_target_range():
    """#65：化神分支可有世界 Boss 手感，但仍受 20-80 总挑战数护栏约束。"""
    challenges = B.world_boss_kill_challenges("huashen", 4, 2, n=120, profile=B.HUASHEN_BRANCH_GEARED)

    assert 20 <= challenges <= 80


def test_huashen_maps_keep_stone_margin_below_stamina_buy():
    from services import shop

    cap = shop.first_buy_cost_per_stamina(4) * 0.75
    for key in TIERS[4]:
        yield_per = B.map_stone_per_stamina(key)
        assert yield_per < cap, f"{key} 产出 {yield_per:.1f} 灵石/精力 未低于化神首买 75%({cap:.1f})"


def test_lianxu_maps_config_and_duration_ranges():
    from config.maps import MAPS
    from services import explore

    expected = {
        "太初雾泽": {"stamina": 20, "minutes": (15, 18), "drop": "雾泽虚砂"},
        "虚空裂海": {"stamina": 24, "minutes": (18, 22), "drop": "裂海空髓"},
        "混沌古狱": {"stamina": 28, "minutes": (22, 26), "drop": "混沌残核"},
    }
    for key, cfg in expected.items():
        m = MAPS[key]
        assert m["realm"] == 5
        assert m["stamina"] == cfg["stamina"]
        assert m["minutes"] == cfg["minutes"]
        assert cfg["drop"] in {drop[0] for drop in m["drops"]}
    assert explore._plan_minutes(MAPS["太初雾泽"], False, 1) == 16.5
    assert explore._plan_minutes(MAPS["虚空裂海"], False, 1) == 18
    assert explore._plan_minutes(MAPS["虚空裂海"], False, 2) == 22
    assert explore._plan_minutes(MAPS["混沌古狱"], True, 2) == 26


def test_lianxu_geared_hits_map_gates():
    """spec-v3 M1 T1.4：炼虚门槛按炼虚装备档回归验收。"""
    from config.maps import MAPS

    profile = B.LIANXU_GEARED
    assert B.map_run_winrate(5, 0, "太初雾泽", profile=profile, n=120) >= 0.95
    assert B.map_run_winrate(5, 0, "虚空裂海", profile=profile, n=120) >= 0.65
    assert B.winrate(5, 0, MAPS["虚空裂海"]["boss"], profile=profile, n=120) < 0.05
    assert B.map_run_winrate(5, 0, "混沌古狱", profile=profile, n=120) < 0.05
    assert B.winrate(5, 1, MAPS["虚空裂海"]["boss"], profile=profile, n=120) >= 0.85
    assert B.winrate(5, 1, MAPS["混沌古狱"]["boss"], profile=profile, n=120) < 0.05
    assert B.winrate(5, 2, MAPS["混沌古狱"]["boss"], profile=profile, n=120) >= 0.85
    assert B.map_run_winrate(5, R.num_stages(5) - 1, "混沌古狱", profile=profile, n=120) >= 0.95


def test_huashen_full_buff_cannot_break_lianxu_boss_gates():
    """spec-v3 §3.5：化神满 buff 可摸新图，但炼虚中/难图 Boss 仍不得被打穿。"""
    from config.maps import MAPS

    for profile in (B.HUASHEN_FULL_BUFF_ATK, B.HUASHEN_FULL_BUFF_SURV):
        assert B.winrate(4, R.num_stages(4) - 1, MAPS["虚空裂海"]["boss"], profile=profile, n=120) < 0.05
        assert B.winrate(4, R.num_stages(4) - 1, MAPS["混沌古狱"]["boss"], profile=profile, n=120) < 0.05
        assert B.map_run_winrate(4, R.num_stages(4) - 1, "混沌古狱", profile=profile, n=120) < 0.05


def test_lianxu_maps_keep_stone_margin_below_stamina_buy():
    from services import shop

    cap = shop.first_buy_cost_per_stamina(5) * 0.75
    for key in TIERS[5]:
        yield_per = B.map_stone_per_stamina(key)
        assert yield_per < cap, f"{key} 产出 {yield_per:.1f} 灵石/精力 未低于炼虚首买 75%({cap:.1f})"


def test_huashen_full_buff_lianxu_transition_is_low_efficiency():
    """spec-v3 T0.11：化神满 buff 可磨炼虚中图普通怪，但收益须低于易图。"""
    last = R.num_stages(4) - 1
    profiles = (B.HUASHEN_FULL_BUFF_ATK, B.HUASHEN_FULL_BUFF_SURV)

    for profile in profiles:
        assert B.map_run_winrate(4, last, "太初雾泽", profile=profile, n=120) >= 0.95

    transition_rates = [
        (B.map_run_winrate(4, last, "虚空裂海", profile=profile, n=120), profile)
        for profile in profiles
    ]
    transition, transition_profile = max(transition_rates, key=lambda item: item[0])
    easy_eff = B.effective_map_cult_per_stamina(4, last, "太初雾泽", profile=transition_profile, n=120)
    mid_eff = B.effective_map_cult_per_stamina(4, last, "虚空裂海", profile=transition_profile, n=120)

    assert 0.15 <= transition <= 0.65
    assert 0 < mid_eff < easy_eff


def test_lianxu_maps_are_better_growth_route_than_huashen_maps():
    """spec-v3 T0.11：炼虚圆满碾压化神内容，但成长路线应转向炼虚图。"""
    from config.maps import MAPS

    last = R.num_stages(5) - 1
    assert B.map_run_winrate(5, last, "天外古墟", profile=B.LIANXU_GEARED, n=120) >= 0.98
    best_huashen = max(MAPS[key]["cult"] / MAPS[key]["stamina"] for key in TIERS[4])
    weakest_lianxu = min(MAPS[key]["cult"] / MAPS[key]["stamina"] for key in TIERS[5])
    assert weakest_lianxu > best_huashen


def test_lianxu_progression_profile_hits_weeks_target():
    """spec-v3 T0.11：普通活跃 6~9 周，高活跃不低于 4 周且更快。"""
    profile = B.lianxu_progression_profile()
    ordinary_days = profile["ordinary"]["total_days"]
    high_days = profile["high"]["total_days"]

    assert 42 <= ordinary_days <= 63
    assert 28 <= high_days < ordinary_days


def test_lianxu_first_breakthrough_profile_hits_cycle_targets():
    """spec-v3 T0.11：首枚炼虚丹 2~4 周，期望进炼虚 4~6 周。"""
    profile = B.lianxu_first_breakthrough_profile()

    assert profile["huashen_accessible"] is True
    assert all(source["realm"] <= 4 for source in profile["sources"])
    assert 14 <= profile["first_pill_days"] <= 28
    assert 28 <= profile["entry_days"] <= 42
    assert 1.8 <= profile["expected_attempts"] <= 2.0


def test_m0_lianxu_economy_profiles_cover_two_player_states():
    """spec-v3 T0.11：存量化神余粮档与新进化神现刷档都不能靠买精力套利。"""
    econ = B.m0_lianxu_economy_profiles()
    stored = econ["stored_lianxu"]
    new = econ["new_huashen"]

    assert stored["stamina_cap"] == R.STAMINA_CAP[5]
    assert stored["max_value"] < stored["value_cap"]
    assert all(value < stored["value_cap"] for value in stored["map_values"].values())
    assert new["stamina_cap"] == R.STAMINA_CAP[4]
    assert new["daily_stamina"] <= new["stamina_cap"]
    assert new["route_value"] < new["value_cap"]


# ---- C1: 坊市/活动/飞升产出进反套利校验（spec DoD #3）----

def test_all_realms_content_value_including_drops_under_first_buy():
    """含掉落变现（坊市灵石流）后，全境界最佳内容产出均 < 首买精力成本。

    秘境口径修正（扣入场费、drops 不放大）后，低境界 r0/r1 的微套利消除。
    """
    from services import shop
    for r in range(len(R.REALM_NAMES)):
        cost = shop.first_buy_cost_per_stamina(r)
        value = B.best_content_value_per_stamina(r)
        assert value < cost, (
            f"r{r} 含掉落产出 {value:.1f} 未低于首买 {cost:.1f}，反套利红线失守")


def test_auction_whitelist_material_values_stay_under_buy_margin():
    """spec-v3 T1.5：白名单材料按玩家市场估值后，仍不得打穿买精力刷钱红线。"""
    from services import shop

    assert {"天外残玉", "雾泽虚砂", "裂海空髓", "混沌残核"} <= B.AUCTION_WHITELIST_MATERIALS
    assert B.AUCTION_WHITELIST_REALMS == (4, 5)
    for r in B.AUCTION_WHITELIST_REALMS:
        cap = shop.first_buy_cost_per_stamina(r) * 0.75
        value = B.best_content_market_value_per_stamina(r)
        assert value < cap, (
            f"r{r} 白名单折算产出 {value:.1f} 未低于首买75%红线 {cap:.1f}")


def test_lianxu_daily_loop_stamina_and_market_value_are_self_consistent():
    """spec-v3 M1 DoD：三图+虚空神殿×2+炼虚Boss的日常精力与白名单材料价值自洽。"""
    profile = B.lianxu_daily_loop_profile()

    assert profile["daily_stamina"] == (
        sum(B.MAPS[key]["stamina"] for key in ("太初雾泽", "虚空裂海", "混沌古狱"))
        + B.DUNGEONS["xukong"]["stamina"] * 2
        + B.WORLD_BOSSES["lianxu"]["stamina"]
    )
    assert profile["daily_stamina"] <= profile["stamina_cap"]
    assert profile["max_repeatable_value"] < profile["value_cap"]
    assert profile["max_daily_value"] < profile["value_cap"]


def test_natal_feed_sink_covers_lianxu_materials_and_forge_discount():
    """spec-v3 M5 DoD：本命喂养显式消耗炼虚材料，并只给器修降耗不提上限。"""
    profile = B.natal_feed_sink_profile()

    assert profile["levels"] == tuple(range(2, B.NATAL.MAX_LEVEL + 1))
    assert profile["standard_stone"] == 252_000
    assert profile["forge_stone"] == 226_800
    assert profile["standard_items"]["器魂"] == 70
    assert profile["forge_items"]["器魂"] == 61
    assert profile["forge_stone_discount"] == 25_200
    assert profile["forge_qihun_discount"] == 9
    assert profile["lianxu_items"] == {"雾泽虚砂": 3, "裂海空髓": 3, "混沌残核": 3}
    assert profile["all_lianxu_sources_available"] is True
    for key in B.NATAL_LIANXU_SINK_MATERIALS:
        assert profile["sources"][key], key


def test_dungeon_value_subtracts_entry_and_keeps_drops_unscaled():
    """秘境反套利口径：扣入场费；drops 不受 reward_factor 放大（复刻 _resolve 仅 stone/cult 放大）。"""
    xuanming = B.DUNGEONS["xuanming"]
    gross_stone = (sum(xuanming["stone"]) / 2 * 5.0) / xuanming["stamina"]
    assert B.dungeon_stone_per_stamina("xuanming") < gross_stone           # entry(80) 已扣
    assert B.dungeon_drops_sell_per_stamina("xuanming") == (
        B._drops_sell_expectation(xuanming["drops"]) / xuanming["stamina"])  # drops 不放大


def test_activity_daohang_capped():
    """活动道行须有周上限，防无限刷 → 飞升点膨胀。"""
    prof = B.activity_daohang_profile()
    assert prof["capped"] is True
    assert prof["weekly_cap"] > 0
    assert prof["runs_to_cap"] >= 1


def test_regular_daohang_sources_do_not_bypass_activity_cap():
    """#45：常规道行来源为小额补给，共用周上限且低于活动副本上限。"""
    prof = B.regular_daohang_profile()
    assert prof["unlock_realm"] == 3
    assert prof["under_activity_cap"] is True
    assert prof["weekly_cap"] <= B.activity_daohang_profile()["weekly_cap"]
    assert prof["max_explore"] < prof["weekly_cap"]
    assert prof["max_dungeon"] < prof["weekly_cap"]


def test_ascension_passive_within_clamp_and_nontradeable():
    """飞升被动增益受 §6.3 clamp；飞升点非物品、不可交易。"""
    guard = B.ascension_arbitrage_guard()
    assert guard["within_clamp"] is True
    assert guard["tradeable_violations"] == []


def test_market_critical_materials_not_in_shop():
    """关键突破丹/飞升链材料不得 NPC 直售（坊市套利护栏）。"""
    assert B.market_arbitrage_violations() == []


def _boss(realm: int):
    from config.maps import MAPS
    return MAPS[MAP_OF[realm]]["boss"]
