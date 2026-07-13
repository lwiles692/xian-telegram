from __future__ import annotations

"""平衡 / 经济模拟器（issues #13-#16 的共同地基）。

纯函数,基于 ``services.combat.simulate``,不碰 DB。玩家属性按
``services.character.stats`` 的同样顺序构造(装备平加 → 心法乘算)。
固定 seed=0..N-1,胜率是确定值,可直接做回归断言。

直接运行打印报告::

    python -m tools.balance_sim
"""

import random

from config import realms as R
from config import auction as AUCTION
from config import buffs as BUFFS
from config import daohang as DAOHANG_CFG
from config import dao_paths as DAO
from config import natal as NATAL
from config.ascension import (OVERFLOW_CULTIVATION_PER_POINT, OVERFLOW_WEEKLY_CAP,
                              PASSIVE_CAP, PASSIVES)
from config.bosses import WORLD_BOSSES
from config.dungeons import DUNGEONS
from config.items import ITEMS
from config.maps import MAPS
from config.quests import QUESTS
from config.sects import TASK_STAMINA_REWARD
from config.shop import SHOP_ITEMS
from config.skills import SKILLS
from config.weekly_events import (RUN_DAOHANG_REWARD, RUN_STAMINA_COST, WEEKLY_DAOHANG_CAP)
from services.combat import Combatant, simulate
from services.daily import DAILY_STAMINA_REWARD

# 标准调参档:"满配无词条"——某境界玩家*应当*能通关内容的地板线。
GEARED = {"skills": ["快剑斩", "烈火诀", "回春术", "普攻"],
          "mind": "吐纳诀", "equip": ["玄铁剑", "青木甲", "聚灵佩"]}
STARTER = {"skills": ["快剑斩", "普攻"], "mind": "吐纳诀", "equip": ["新手剑"]}
YUANYING_LEGACY_GEARED = {**GEARED, "mind": "归元心法"}
YUANYING_TREASURE_GEARED = {"skills": ["快剑斩", "烈火诀", "回春术", "普攻"],
                            "mind": "归元心法", "equip": ["天魔刃", "战魂甲", "古战佩"]}
HUASHEN_GEARED = {"skills": ["快剑斩", "烈火诀", "回春术", "普攻"],
                  "mind": "归元心法", "equip": ["陨星剑", "幽都甲", "太虚佩"]}
HUASHEN_BRANCH_GEARED = {"skills": ["快剑斩", "烈火诀", "回春术", "普攻"],
                         "mind": "归元心法", "equip": ["星河幡", "星陨袍", "幽都铃"]}
LIANXU_HUASHEN_GEARED = HUASHEN_GEARED
LIANXU_EQUIP_KEYS = ["太初虚刃", "玄冥空甲", "混沌灵佩"]
LIANXU_EQUIPMENT_PROFILE = {**HUASHEN_GEARED, "equip": LIANXU_EQUIP_KEYS}
LIANXU_GEARED = LIANXU_EQUIPMENT_PROFILE
# 元婴圆满满 buff 上界档：现役元婴装备 + 可叠满临时/福利 buff（推到 §6.3 合算上限）。
# 红线护栏（spec §3.2）：即便如此仍不得稳定刷化神中/难 Boss。M0 阶段不含道途。
YUANYING_FULL_BUFF = {
    **YUANYING_TREASURE_GEARED,
    "extra_pct": {"atk": BUFFS.ATTACK_PCT_CAP, "crit": BUFFS.ATTACK_PCT_CAP,
                  "hp": BUFFS.SURVIVAL_PCT_CAP, "df": BUFFS.SURVIVAL_PCT_CAP},
}
ASCENSION_FULL_PASSIVES = {key: PASSIVE_CAP for key in PASSIVES}
HUASHEN_FULL_BUFF_ATK = {
    **HUASHEN_GEARED,
    "dao_path": "sword",
    "dao_rank": len(DAO.RANK_NAMES) - 1,
    "dao_refine": DAO.REFINE_MAX_LEVEL,
    "ascension_passives": ASCENSION_FULL_PASSIVES,
    "extra_pct": {"atk": BUFFS.ATTACK_PCT_CAP, "crit": BUFFS.ATTACK_PCT_CAP},
}
HUASHEN_FULL_BUFF_SURV = {
    **HUASHEN_GEARED,
    "dao_path": "body",
    "dao_rank": len(DAO.RANK_NAMES) - 1,
    "dao_refine": DAO.REFINE_MAX_LEVEL,
    "ascension_passives": ASCENSION_FULL_PASSIVES,
    "extra_pct": {"hp": BUFFS.SURVIVAL_PCT_CAP, "df": BUFFS.SURVIVAL_PCT_CAP},
}
DAO_MAX_PROFILES = {
    key: {**GEARED, "dao_path": key, "dao_rank": len(DAO.RANK_NAMES) - 1}
    for key in DAO.DAO_PATHS
}
DAO_MAX_REFINED_PROFILES = {
    key: {**profile, "dao_refine": DAO.REFINE_MAX_LEVEL}
    for key, profile in DAO_MAX_PROFILES.items()
}

# 每张图/秘境对应的"解锁境界"。
CONTENT_REALM = {
    "后山": 0,
    "妖兽森林": 1,
    "万妖岭": 2,
    "上古战场": 3,
    "星陨海": 4,
    "太初雾泽": 5,
    "虚空裂海": 5,
    "混沌古狱": 5,
    "xukong": 5,
}


def ascension_passive_bonuses(profile=GEARED) -> dict:
    bonuses = {}
    for key, level in profile.get("ascension_passives", {}).items():
        if key in PASSIVES:
            bonuses[key] = min(PASSIVE_CAP, max(0, int(level))) * 0.01
    return bonuses


def build_player_stats(realm: int, stage: int, profile=GEARED) -> dict:
    base = R.base_stats(realm, stage)
    pct_bonus = {key: 0.0 for key in R.STAT_KEYS}
    for key in profile.get("equip", []):
        for k, v in ITEMS.get(key, {}).get("bonus", {}).items():
            if k.endswith("_pct"):
                stat_key = k[:-4]
                if stat_key in pct_bonus:
                    pct_bonus[stat_key] += float(v)
            else:
                base[k] = base.get(k, 0) + v
    mind = SKILLS.get(profile.get("mind"))
    if mind:
        for k, v in mind.get("bonus", {}).items():
            if k.endswith("_pct"):
                sk = k[:-4]
                if sk in pct_bonus:
                    pct_bonus[sk] += float(v)
            else:
                base[k] = base.get(k, 0) + v
    for k, v in DAO.bonuses_for(
            profile.get("dao_path", ""), profile.get("dao_rank", 0),
            profile.get("dao_refine", 0)).items():
        if k.endswith("_pct"):
            sk = k[:-4]
            if sk in pct_bonus:
                pct_bonus[sk] += float(v)
        elif k in R.STAT_KEYS:
            base[k] = base.get(k, 0) + int(v)
    for k, v in ascension_passive_bonuses(profile).items():
        if k.endswith("_pct"):
            sk = k[:-4]
            if sk in pct_bonus:
                pct_bonus[sk] += float(v)
    for k, v in profile.get("extra_pct", {}).items():
        if k in pct_bonus:
            pct_bonus[k] += float(v)
    for k, pct in pct_bonus.items():
        cap = BUFFS.ATTACK_PCT_CAP if k in BUFFS.ATTACK_STATS else BUFFS.SURVIVAL_PCT_CAP
        applied = min(cap, max(0.0, pct))
        if applied:
            base[k] = int(base.get(k, 0) * (1 + applied))
    return base


def player(realm: int, stage: int, profile=GEARED) -> Combatant:
    st = build_player_stats(realm, stage, profile)
    return Combatant(name="道友", hp=st["hp"], mp=st["mp"], atk=st["atk"],
                     df=st["df"], spd=st["spd"], crit=st["crit"],
                     skills=list(profile["skills"]))


def _mob(src: dict) -> Combatant:
    return Combatant(name=src["name"], hp=src["hp"], mp=src.get("mp", 50),
                     atk=src["atk"], df=src["df"], spd=src["spd"],
                     crit=src["crit"], skills=list(src["skills"]))


def winrate(realm: int, stage: int, mob_src: dict, profile=GEARED, n: int = 300) -> float:
    wins = 0
    for s in range(n):
        p = player(realm, stage, profile)
        if simulate(p, _mob(mob_src), seed=s, max_rounds=None)["winner"] is p:
            wins += 1
    return wins / n


def map_winrates(realm: int, stage: int, map_key: str, profile=GEARED, n: int = 300):
    """返回 (平均小怪胜率, Boss 胜率)。"""
    m = MAPS[map_key]
    mob = sum(winrate(realm, stage, mb, profile, n) for mb in m["mobs"]) / len(m["mobs"])
    boss = winrate(realm, stage, m["boss"], profile, n)
    return mob, boss


def map_run_winrate(realm: int, stage: int, map_key: str,
                    profile=GEARED, n: int = 300) -> float:
    """复刻 explore._resolve 的小怪连战(按难度 1/1-2/2-3 场,血量结转)运行胜率。"""
    from services.explore import DIFFICULTY_PLAN
    m = MAPS[map_key]
    lo, hi = DIFFICULTY_PLAN.get(m.get("difficulty", "易"), DIFFICULTY_PLAN["易"])["enc"]
    wins = 0
    for s in range(n):
        rng = random.Random(s)
        p = player(realm, stage, profile)
        ok = True
        for _ in range(rng.randint(lo, hi)):
            res = simulate(
                p, _mob(rng.choice(m["mobs"])),
                seed=rng.randint(1, 10_000_000), max_rounds=None)
            if res["winner"] is not p:
                ok = False
                break
            p.hp = max(1, res["a_hp"])
        wins += ok
    return wins / n


def dungeon_clear_fraction(realm: int, stage: int, dungeon_key: str,
                           profile=GEARED, n: int = 200) -> float:
    """平均通关层数比例,复刻 services.dungeon 的逐层血量结转。"""
    d = DUNGEONS[dungeon_key]
    total = 0.0
    for s in range(n):
        rng = random.Random(s)
        p = player(realm, stage, profile)
        cleared = 0
        for layer in range(1, d["layers"] + 1):
            mob_src = d["boss"] if layer == d["layers"] else rng.choice(d["mobs"])
            res = simulate(
                p, _mob(mob_src),
                seed=rng.randint(1, 10_000_000), max_rounds=None)
            if res["winner"] is not p:
                break
            cleared += 1
            p.hp = max(1, res["a_hp"])
        total += cleared / d["layers"]
    return total / n


def boss_damage_per_challenge(realm: int, stage: int, boss_key: str,
                              profile=GEARED, n: int = 200) -> float:
    """单次挑战对世界 Boss 战斗假人造成的平均伤害。"""
    cfg = WORLD_BOSSES[boss_key]
    combat = cfg["combat"]
    total = 0
    for s in range(n):
        p = player(realm, stage, profile)
        target = _mob(combat)
        res = simulate(p, target, seed=s)
        total += max(1, target.max_hp - res["d_hp"])
    return total / n


def world_boss_kill_challenges(boss_key: str, realm: int, stage: int, n: int = 200, profile=GEARED) -> float:
    """该档玩家击杀世界 Boss 所需的总挑战次数 = total_hp / 单次伤害。"""
    cfg = WORLD_BOSSES[boss_key]
    return cfg["total_hp"] / boss_damage_per_challenge(realm, stage, boss_key, profile=profile, n=n)


def breakthrough_rate_with_profile(base_rate: float, profile=GEARED) -> float:
    bonus = DAO.bonuses_for(
        profile.get("dao_path", ""), profile.get("dao_rank", 0),
        profile.get("dao_refine", 0))
    return min(0.95, base_rate + float(bonus.get("alchemy_pct", 0)))


def forge_quality_score(profile=GEARED) -> float:
    bonus = DAO.bonuses_for(
        profile.get("dao_path", ""), profile.get("dao_rank", 0),
        profile.get("dao_refine", 0))
    return 1.0 + float(bonus.get("forge_pct", 0))


def seclusion_efficiency(profile=GEARED) -> float:
    bonus = DAO.bonuses_for(
        profile.get("dao_path", ""), profile.get("dao_rank", 0),
        profile.get("dao_refine", 0))
    asc_bonus = ascension_passive_bonuses(profile)
    raw = float(bonus.get("seclusion_pct", 0)) + float(asc_bonus.get("seclusion_pct", 0))
    return 1.0 + min(BUFFS.SECLUSION_PCT_CAP, max(0.0, raw))


def effective_map_cult_per_stamina(realm: int, stage: int, map_key: str,
                                   profile=GEARED, n: int = 120) -> float:
    """按连战成功率折算的修为/精力，用于近二值战斗的过渡收益口径。"""
    m = MAPS[map_key]
    return m["cult"] / m["stamina"] * map_run_winrate(realm, stage, map_key, profile=profile, n=n)


def _seclusion_daily_gain(cost: int, root_bone: int, hours_per_day: float, realm: int = 5) -> float:
    return cost * hours_per_day * (1 + max(0, root_bone) / 200) / R.SECLUSION_STAGE_HOURS[realm]


def lianxu_progression_days(root_bone: int, seclusion_hours_per_day: float,
                            daily_stamina: int, stage_maps: tuple[str, str, str],
                            profile=LIANXU_GEARED, n: int = 120) -> dict:
    """炼虚初期→圆满的天数估算：三段推进到圆满，闭关 + 每日炼虚图修为。"""
    stages = []
    total = 0.0
    for stage, map_key in enumerate(stage_maps):
        cost = R.advance_cost(5, stage)
        seclusion = _seclusion_daily_gain(cost, root_bone, seclusion_hours_per_day, realm=5)
        m = MAPS[map_key]
        runrate = map_run_winrate(5, stage, map_key, profile=profile, n=n)
        map_gain = daily_stamina / m["stamina"] * m["cult"] * runrate
        daily_gain = seclusion + map_gain
        days = cost / daily_gain
        stages.append({
            "stage": stage,
            "map": map_key,
            "runrate": runrate,
            "daily_gain": daily_gain,
            "days": days,
        })
        total += days
    return {"total_days": total, "stages": stages}


def lianxu_stamina_supply_profile() -> dict:
    """炼虚日精力供给：一天一管、早晚两管、完全利用自然恢复三档。"""
    quest_reward = sum(
        int(QUESTS[key]["reward"].get("stamina", 0))
        for key in ("daily_explore", "daily_craft", "daily_pvp_win")
    )
    daily_reward = DAILY_STAMINA_REWARD + quest_reward + TASK_STAMINA_REWARD
    cap = R.STAMINA_CAP[5]
    natural = round(24 * 3600 / R.STAMINA_REGEN_SECONDS[5])
    return {
        "daily_reward": daily_reward,
        "one_session": cap + daily_reward,
        "two_sessions": cap * 2 + daily_reward,
        "maximum": natural + daily_reward,
    }


def lianxu_progression_profile() -> dict:
    """新精力曲线推进时长：普通 4~5 周，高活跃 2~3 周，满勤不低于 2 周。"""
    supply = lianxu_stamina_supply_profile()
    ordinary = lianxu_progression_days(
        root_bone=60,
        seclusion_hours_per_day=18,
        daily_stamina=supply["one_session"],
        stage_maps=("太初雾泽", "太初雾泽", "太初雾泽"),
        n=120,
    )
    high = lianxu_progression_days(
        root_bone=70,
        seclusion_hours_per_day=22,
        daily_stamina=supply["two_sessions"],
        stage_maps=("太初雾泽", "虚空裂海", "混沌古狱"),
        n=120,
    )
    maximum = lianxu_progression_days(
        root_bone=70,
        seclusion_hours_per_day=22,
        daily_stamina=supply["maximum"],
        stage_maps=("太初雾泽", "虚空裂海", "混沌古狱"),
        n=120,
    )
    return {"ordinary": ordinary, "high": high, "maximum": maximum,
            "stamina_supply": supply}


def _drop_weight(drops, key: str) -> float:
    return next((float(weight) for item, weight, *_ in drops if item == key), 0.0)


def expected_lianxu_breakthrough_attempts() -> float:
    """45% 基础率 + 每败 10% 保底，95% 封顶下的期望消耗丹数。"""
    base = R.BIG_BREAKTHROUGH[5]["base_rate"]
    fail_prob = 1.0
    expected = 0.0
    for streak in range(20):
        expected += fail_prob
        rate = min(0.95, base + streak * 0.10)
        fail_prob *= (1 - rate)
        if fail_prob < 1e-9:
            break
    return expected


def lianxu_first_breakthrough_profile() -> dict:
    """首枚炼虚丹与进入炼虚的期望周期，来源限定为化神可及内容。"""
    tianwai = MAPS["天外古墟"]["drops"]
    taixu = DUNGEONS["taixu"]["drops"]
    daily_tianwai_runs = 1
    daily_taixu_runs = 2
    boss_frontline_scrap_per_day = 0.04
    direct_pill_per_day = daily_tianwai_runs * _drop_weight(tianwai, "炼虚丹") / 100
    scrap_per_day = (
        daily_tianwai_runs * _drop_weight(tianwai, "炼虚丹残方") / 100
        + daily_taixu_runs * _drop_weight(taixu, "炼虚丹残方") / 100
        + boss_frontline_scrap_per_day
    )
    pill_equiv_per_day = direct_pill_per_day + scrap_per_day / 4
    first_pill_days = 1 / pill_equiv_per_day
    expected_attempts = expected_lianxu_breakthrough_attempts()
    sources = [
        {"kind": "map", "key": "天外古墟", "realm": MAPS["天外古墟"]["realm"]},
        {"kind": "dungeon", "key": "taixu", "realm": DUNGEONS["taixu"]["realm"]},
        {"kind": "world_boss", "key": "huashen", "realm": WORLD_BOSSES["huashen"]["realm"]},
    ]
    return {
        "daily_tianwai_runs": daily_tianwai_runs,
        "daily_taixu_runs": daily_taixu_runs,
        "boss_frontline_scrap_per_day": boss_frontline_scrap_per_day,
        "direct_pill_per_day": direct_pill_per_day,
        "scrap_per_day": scrap_per_day,
        "pill_equiv_per_day": pill_equiv_per_day,
        "first_pill_days": first_pill_days,
        "expected_attempts": expected_attempts,
        "entry_days": first_pill_days * expected_attempts,
        "sources": sources,
        "huashen_accessible": all(src["realm"] <= 4 for src in sources),
    }


# ---- 经济:套利 ----

def map_stone_per_stamina(map_key: str) -> float:
    """单位精力的灵石*期望*：含妖王双倍奖励按 boss_rate 计入（explore._resolve mult=2）。"""
    m = MAPS[map_key]
    avg = sum(m["stone"]) / 2
    expected = avg * (1 + m["boss_rate"])   # 妖王战灵石×2
    return expected / m["stamina"]


def dungeon_stone_per_stamina(dungeon_key: str, reward_factor: float = 5.0) -> float:
    """秘境净灵石/精力：满层 stone(×reward_factor，复刻 _resolve 的 uniform(4,6)) 扣入场费。"""
    d = DUNGEONS[dungeon_key]
    gross = (sum(d["stone"]) / 2) * reward_factor
    return (gross - float(d.get("entry_stone", 0))) / d["stamina"]


def best_content_stone_per_stamina(realm: int) -> float:
    """该境界可进入的最佳灵石产出(图与秘境取较高者)。"""
    vals = [map_stone_per_stamina(k) for k, m in MAPS.items() if m["realm"] <= realm]
    vals += [dungeon_stone_per_stamina(k) for k, d in DUNGEONS.items() if d["realm"] <= realm]
    return max(vals) if vals else 0.0


# ---- 经济:新增产出反套利（M3/M4/M5，spec DoD #3）----
# 坊市灵石流 = 内容掉落物变现（NPC 回收 / 坊市转手）的期望灵石价值；
# 活动道行 / 飞升点为另一维产出，靠周上限与硬上限封顶。三者均须显式校验
# 不破坏"内容产出/精力 < 首买精力成本/精力"的反套利红线。

AUCTION_WHITELIST_MATERIALS = AUCTION.MATERIAL_WHITELIST
AUCTION_WHITELIST_REALMS = (4, 5)
WHITELIST_MARKET_VALUE_MULTIPLIER = AUCTION.MATERIAL_MARKET_VALUE_MULTIPLIER


def auction_material_value(key: str) -> float:
    """M1/T1.5 白名单材料估值：按 NPC 回收价三倍折算玩家市场价格。"""
    sell = float(ITEMS.get(key, {}).get("sell", 0) or 0)
    if key in AUCTION_WHITELIST_MATERIALS:
        return sell * WHITELIST_MARKET_VALUE_MULTIPLIER
    return sell


def _drops_value_expectation(drops, value_fn) -> float:
    """drops [(key, weight, qmin, qmax)] 的单次期望变现价值。

    复刻 explore._roll_drops：weight/100 为掉率，数量 randint(qmin,qmax) 取均值。
    绑定材料 value=0 自然不计入（不构成可变现产出）。
    """
    total = 0.0
    for key, weight, qmin, qmax in drops:
        chance = min(100.0, float(weight)) / 100.0
        total += chance * (qmin + qmax) / 2 * float(value_fn(key))
    return total


def _drops_sell_expectation(drops) -> float:
    """drops 的单次期望 NPC 回收价值。"""
    return _drops_value_expectation(drops, lambda key: ITEMS.get(key, {}).get("sell", 0) or 0)


def _drops_market_expectation(drops) -> float:
    """drops 的单次期望玩家市场价值；白名单材料按 T1.5 保守估值。"""
    return _drops_value_expectation(drops, auction_material_value)


def map_drops_sell_per_stamina(map_key: str) -> float:
    return _drops_sell_expectation(MAPS[map_key]["drops"]) / MAPS[map_key]["stamina"]


def map_drops_market_per_stamina(map_key: str) -> float:
    return _drops_market_expectation(MAPS[map_key]["drops"]) / MAPS[map_key]["stamina"]


def dungeon_drops_sell_per_stamina(dungeon_key: str) -> float:
    """秘境掉落 sell/精力：drops 不受 reward_factor 放大（复刻 _resolve：仅 stone/cult 放大）。"""
    d = DUNGEONS[dungeon_key]
    return _drops_sell_expectation(d["drops"]) / d["stamina"]


def dungeon_drops_market_per_stamina(dungeon_key: str) -> float:
    """秘境掉落市场价值/精力：drops 不受 reward_factor 放大，白名单材料按保守成交价。"""
    d = DUNGEONS[dungeon_key]
    return _drops_market_expectation(d["drops"]) / d["stamina"]


def best_content_value_per_stamina(realm: int) -> float:
    """含掉落变现(灵石+可回收物)的最佳内容产出/精力。反套利红线须 < 首买成本/精力。"""
    vals = [map_stone_per_stamina(k) + map_drops_sell_per_stamina(k)
            for k, m in MAPS.items() if m["realm"] <= realm]
    vals += [dungeon_stone_per_stamina(k) + dungeon_drops_sell_per_stamina(k)
             for k, d in DUNGEONS.items() if d["realm"] <= realm]
    return max(vals) if vals else 0.0


def world_boss_drops_market_value(boss_key: str) -> float:
    """世界 Boss 击杀总掉落的玩家市场估值；按整只 Boss 奖池折算。"""
    return sum(auction_material_value(key) * int(qty)
               for key, qty in WORLD_BOSSES[boss_key]["drops"].items())


def world_boss_value_per_stamina(boss_key: str, realm: int, stage: int,
                                 n: int = 120, profile=GEARED) -> float:
    """世界 Boss 按击杀总挑战数折算的单精力价值，用于日常项审计。"""
    cfg = WORLD_BOSSES[boss_key]
    challenges = world_boss_kill_challenges(boss_key, realm, stage, n=n, profile=profile)
    total_value = cfg["stone_pool"] + world_boss_drops_market_value(boss_key)
    return total_value / max(1.0, challenges * cfg["stamina"])


def best_content_market_value_per_stamina(realm: int) -> float:
    """白名单材料按玩家市场估值后，图/秘境/世界 Boss 的最佳产出/精力。"""
    vals = [map_stone_per_stamina(k) + map_drops_market_per_stamina(k)
            for k, m in MAPS.items() if m["realm"] <= realm]
    vals += [dungeon_stone_per_stamina(k) + dungeon_drops_market_per_stamina(k)
             for k, d in DUNGEONS.items() if d["realm"] <= realm]
    vals += [world_boss_value_per_stamina(
        k, b["realm"], min(2, R.num_stages(b["realm"]) - 1),
        profile=LIANXU_GEARED if b["realm"] == 5 else HUASHEN_GEARED if b["realm"] == 4 else GEARED)
        for k, b in WORLD_BOSSES.items() if b["realm"] <= realm]
    return max(vals) if vals else 0.0


def lianxu_daily_loop_profile() -> dict:
    """M1/T1.5 炼虚日常闭环：三图各一次、虚空神殿两次、炼虚 Boss 一次。"""
    from services import shop
    map_keys = ("太初雾泽", "虚空裂海", "混沌古狱")
    map_values = {
        key: map_stone_per_stamina(key) + map_drops_market_per_stamina(key)
        for key in map_keys
    }
    xukong_value = dungeon_stone_per_stamina("xukong") + dungeon_drops_market_per_stamina("xukong")
    boss_value = world_boss_value_per_stamina("lianxu", 5, 2, n=120, profile=LIANXU_GEARED)
    daily_stamina = (
        sum(MAPS[key]["stamina"] for key in map_keys)
        + DUNGEONS["xukong"]["stamina"] * DUNGEONS["xukong"]["daily_limit"]
        + WORLD_BOSSES["lianxu"]["stamina"]
    )
    first_buy = shop.first_buy_cost_per_stamina(5)
    return {
        "stamina_cap": R.STAMINA_CAP[5],
        "daily_stamina": daily_stamina,
        "first_buy": first_buy,
        "value_cap": first_buy * 0.75,
        "map_values": map_values,
        "xukong_value": xukong_value,
        "boss_value": boss_value,
        "max_repeatable_value": max((*map_values.values(), xukong_value)),
        "max_daily_value": max((*map_values.values(), xukong_value, boss_value)),
    }


NATAL_LIANXU_SINK_MATERIALS = ("雾泽虚砂", "裂海空髓", "混沌残核")


def _add_cost_items(total: dict[str, int], items: dict) -> None:
    for key, qty in items.items():
        total[key] = total.get(key, 0) + int(qty)


def _material_sources(key: str) -> list[str]:
    sources = []
    for map_key, cfg in MAPS.items():
        if _drop_weight(cfg["drops"], key) > 0:
            sources.append(map_key)
    for dungeon_key, cfg in DUNGEONS.items():
        if _drop_weight(cfg["drops"], key) > 0:
            sources.append(cfg["name"])
    for boss_key, cfg in WORLD_BOSSES.items():
        if key in cfg["drops"]:
            sources.append(cfg["name"])
    return sources


def natal_feed_sink_profile() -> dict:
    """M5 本命喂养 sink：显式核算 2-10 级材料消耗与炼虚材料来源覆盖。"""
    levels = tuple(range(2, NATAL.MAX_LEVEL + 1))
    standard_items: dict[str, int] = {}
    forge_items: dict[str, int] = {}
    standard_stone = 0
    forge_stone = 0
    per_level = {}
    for level in levels:
        cost = NATAL.feed_cost(level)
        forge_cost = NATAL.feed_cost(level, forge_path=True)
        standard_stone += int(cost["stone"])
        forge_stone += int(forge_cost["stone"])
        _add_cost_items(standard_items, cost["items"])
        _add_cost_items(forge_items, forge_cost["items"])
        per_level[level] = {"cost": cost, "forge_cost": forge_cost}
    sources = {key: _material_sources(key) for key in NATAL_LIANXU_SINK_MATERIALS}
    lianxu_items = {key: standard_items.get(key, 0) for key in NATAL_LIANXU_SINK_MATERIALS}
    return {
        "levels": levels,
        "per_level": per_level,
        "standard_stone": standard_stone,
        "forge_stone": forge_stone,
        "standard_items": standard_items,
        "forge_items": forge_items,
        "lianxu_items": lianxu_items,
        "sources": sources,
        "all_lianxu_sources_available": all(sources[key] for key in NATAL_LIANXU_SINK_MATERIALS),
        "forge_stone_discount": standard_stone - forge_stone,
        "forge_qihun_discount": standard_items.get("器魂", 0) - forge_items.get("器魂", 0),
    }


def activity_daohang_profile() -> dict:
    """活动道行(M4)限流：周上限封顶防肝度失控(spec T4.1)。

    道行→飞升试炼(TRIAL_DAOHANG_COST:TRIAL_POINT_REWARD=500:1)→飞升点，
    受周上限与飞升被动硬上限双重约束。
    """
    runs_to_cap = -(-WEEKLY_DAOHANG_CAP // RUN_DAOHANG_REWARD)   # ceil(cap/per_run)
    return {
        "weekly_cap": WEEKLY_DAOHANG_CAP,
        "per_run": RUN_DAOHANG_REWARD,
        "stamina_per_run": RUN_STAMINA_COST,
        "runs_to_cap": runs_to_cap,
        "capped": WEEKLY_DAOHANG_CAP > 0 and RUN_DAOHANG_REWARD > 0,
    }


def regular_daohang_profile() -> dict:
    """#45 常规玩法道行限流：小额来源共用周上限，不能越过活动副本定位。"""
    max_explore = max(DAOHANG_CFG.EXPLORE_DAOHANG_BY_DIFFICULTY.values()) + DAOHANG_CFG.EXPLORE_BOSS_BONUS
    max_dungeon = max(
        d["layers"] * DAOHANG_CFG.DUNGEON_DAOHANG_PER_LAYER + DAOHANG_CFG.DUNGEON_CLEAR_BONUS
        for d in DUNGEONS.values())
    max_boss_rank = max(DAOHANG_CFG.WORLD_BOSS_RANK_DAOHANG)
    max_pvp_rank = max(DAOHANG_CFG.PVP_WEEKLY_DAOHANG_BY_RANK)
    return {
        "unlock_realm": DAOHANG_CFG.UNLOCK_REALM,
        "weekly_cap": DAOHANG_CFG.REGULAR_WEEKLY_CAP,
        "max_explore": max_explore,
        "max_dungeon": max_dungeon,
        "max_boss_rank": max_boss_rank,
        "max_pvp_rank": max_pvp_rank,
        "under_activity_cap": DAOHANG_CFG.REGULAR_WEEKLY_CAP <= WEEKLY_DAOHANG_CAP,
    }


# 飞升点为账号级数值，非物品（不在 ITEMS/SHOP，天然不可交易）。
_ASCENSION_TRADEABLE_KEYS = ("飞升点",)


def ascension_arbitrage_guard() -> dict:
    """飞升点反套利：凝点周限、被动硬上限与 §6.3 clamp 共同约束。"""
    max_single_pct = PASSIVE_CAP * 0.01
    return {
        "passive_cap": PASSIVE_CAP,
        "overflow_cultivation_per_point": OVERFLOW_CULTIVATION_PER_POINT,
        "overflow_weekly_cap": OVERFLOW_WEEKLY_CAP,
        "max_single_pct": max_single_pct,
        "within_clamp": max_single_pct <= min(BUFFS.ATTACK_PCT_CAP, BUFFS.SURVIVAL_PCT_CAP),
        "tradeable_violations": [k for k in _ASCENSION_TRADEABLE_KEYS
                                 if k in ITEMS or k in SHOP_ITEMS],
    }


# 坊市套利护栏：关键成长材料不得进 NPC 直售（否则内容门槛被灵石绕过）。
_MARKET_BANNED_FROM_SHOP = (
    "化神丹", "化神丹方", "化神丹残方",
    "炼虚丹", "炼虚丹方", "炼虚丹残方",
    "转修令",
)


def market_arbitrage_violations() -> list[str]:
    """关键突破丹/飞升链材料不得在 NPC 直售；运行时 market 仅放行 bound=0（绑定不可上架）。"""
    return [k for k in _MARKET_BANNED_FROM_SHOP if k in SHOP_ITEMS]


def m0_lianxu_economy_profiles() -> dict:
    """M0 经济两档：存量炼虚图刷图档、新进化神首破日程档。"""
    from services import shop
    lianxu_keys = ("太初雾泽", "虚空裂海", "混沌古狱")
    lianxu_values = {
        key: map_stone_per_stamina(key) + map_drops_sell_per_stamina(key)
        for key in lianxu_keys
    }
    huashen_daily_stamina = (
        DUNGEONS["taixu"]["stamina"] * 2
        + WORLD_BOSSES["huashen"]["stamina"]
        + MAPS["天外古墟"]["stamina"]
    )
    return {
        "stored_lianxu": {
            "stamina_cap": R.STAMINA_CAP[5],
            "first_buy": shop.first_buy_cost_per_stamina(5),
            "value_cap": shop.first_buy_cost_per_stamina(5) * 0.75,
            "map_values": lianxu_values,
            "max_value": max(lianxu_values.values()),
        },
        "new_huashen": {
            "stamina_cap": R.STAMINA_CAP[4],
            "daily_stamina": huashen_daily_stamina,
            "first_buy": shop.first_buy_cost_per_stamina(4),
            "value_cap": shop.first_buy_cost_per_stamina(4) * 0.75,
            "route_value": max(
                dungeon_stone_per_stamina("taixu") + dungeon_drops_sell_per_stamina("taixu"),
                map_stone_per_stamina("天外古墟") + map_drops_sell_per_stamina("天外古墟"),
            ),
        },
    }


# ---- 报告 ----

def _bar(x: float) -> str:
    return "█" * int(round(x * 20))


def report() -> None:
    print("=" * 78)
    print("玩家属性(满配无词条)  hp/atk/df/spd/crit")
    for r in range(len(R.REALM_NAMES)):
        for stage in (0, R.num_stages(r) - 1):
            st = build_player_stats(r, stage, GEARED)
            print(f"  {R.realm_label(r, stage):<12} "
                  f"hp{st['hp']:>6} atk{st['atk']:>5} df{st['df']:>5} "
                  f"spd{st['spd']:>4} crit{st['crit']:>4}")
    print("-" * 78)
    print("Issue #65 新法宝 profile 对照")
    for label, realm, stage, profile in (
            ("元婴旧三件", 3, 0, YUANYING_LEGACY_GEARED),
            ("元婴新三件", 3, 0, YUANYING_TREASURE_GEARED),
            ("化神主线", 4, 0, HUASHEN_GEARED),
            ("化神分支", 4, 0, HUASHEN_BRANCH_GEARED),
    ):
        st = build_player_stats(realm, stage, profile)
        print(f"  {label:<8} {R.realm_label(realm, stage):<10} "
              f"hp{st['hp']:>6} mp{st['mp']:>5} atk{st['atk']:>5} df{st['df']:>5} "
              f"spd{st['spd']:>4} crit{st['crit']:>4}")
    print("=" * 78)
    print("地图胜率(满配):  小怪=按难度连战运行胜率, Boss=单场   [易可刷 / 中有险 / 难需成长]")
    for mkey, m in MAPS.items():
        r = m["realm"]
        last = R.num_stages(r) - 1
        e_run = map_run_winrate(r, 0, mkey)
        _, e_boss = map_winrates(r, 0, mkey)
        f_run = map_run_winrate(r, last, mkey)
        _, f_boss = map_winrates(r, last, mkey)
        print(f"  {m['name']:<10}(r{r}) 入门 连战{e_run*100:5.1f}% Boss{e_boss*100:5.1f}%"
              f"   圆满 连战{f_run*100:5.1f}% Boss{f_boss*100:5.1f}%")
    print("-" * 78)
    print("秘境平均通关层比例(满配):  解锁初期 → 圆满   [目标 入门至少过半,部分档位可接近通关]")
    for dkey, d in DUNGEONS.items():
        r = d["realm"]
        last = R.num_stages(r) - 1
        profile = LIANXU_GEARED if r == 5 else HUASHEN_GEARED if r == 4 else GEARED
        e = dungeon_clear_fraction(r, 0, dkey, profile=profile)
        f = dungeon_clear_fraction(r, last, dkey, profile=profile)
        print(f"  {d['name']:<10}(r{r}) 入门 {e*100:5.1f}% {_bar(e):<20} 圆满 {f*100:5.1f}%")
    print("-" * 78)
    print("道途淬炼护栏: 满淬炼体修秘境推进 / 剑修入门 Boss 门槛")
    body = DAO_MAX_PROFILES["body"]
    body_refined = DAO_MAX_REFINED_PROFILES["body"]
    sword = DAO_MAX_PROFILES["sword"]
    sword_refined = DAO_MAX_REFINED_PROFILES["sword"]
    body_taixu = dungeon_clear_fraction(4, 0, "taixu", profile=body)
    body_taixu_refined = dungeon_clear_fraction(4, 0, "taixu", profile=body_refined)
    sword_xingyun = winrate(4, 0, MAPS["星陨海"]["boss"], profile=sword)
    sword_xingyun_refined = winrate(4, 0, MAPS["星陨海"]["boss"], profile=sword_refined)
    print(f"  体修 太虚天门(r4入门) 未淬炼 {body_taixu*100:5.1f}%"
          f" → 满淬炼 {body_taixu_refined*100:5.1f}%")
    print(f"  剑修 星陨海Boss(r4入门) 未淬炼 {sword_xingyun*100:5.1f}%"
          f" → 满淬炼 {sword_xingyun_refined*100:5.1f}%")
    print("-" * 78)
    print("M0 化神圆满满 buff 上界档: 满道途 + 满淬炼 + 飞升被动 + clamp 顶")
    for label, profile in (
            ("HUASHEN_FULL_BUFF_ATK", HUASHEN_FULL_BUFF_ATK),
            ("HUASHEN_FULL_BUFF_SURV", HUASHEN_FULL_BUFF_SURV),
    ):
        st = build_player_stats(4, R.num_stages(4) - 1, profile)
        taixu = dungeon_clear_fraction(4, R.num_stages(4) - 1, "taixu", profile=profile, n=120)
        huashen_boss = world_boss_kill_challenges("huashen", 4, 2, n=120, profile=profile)
        print(f"  {label:<22} hp{st['hp']:>6} atk{st['atk']:>5} df{st['df']:>5} "
              f"crit{st['crit']:>4} 太虚{taixu*100:5.1f}% 化神Boss≈{huashen_boss:5.1f}次")
    print("-" * 78)
    print("M0 炼虚门槛/周期定稿(T0.11): 化神上界、炼虚锚点、首破与经济")
    last4 = R.num_stages(4) - 1
    for label, profile in (
            ("化神攻击上界", HUASHEN_FULL_BUFF_ATK),
            ("化神生存上界", HUASHEN_FULL_BUFF_SURV),
    ):
        easy_run = map_run_winrate(4, last4, "太初雾泽", profile=profile, n=120)
        mid_run = map_run_winrate(4, last4, "虚空裂海", profile=profile, n=120)
        hard_run = map_run_winrate(4, last4, "混沌古狱", profile=profile, n=120)
        easy_eff = effective_map_cult_per_stamina(4, last4, "太初雾泽", profile=profile, n=120)
        mid_eff = effective_map_cult_per_stamina(4, last4, "虚空裂海", profile=profile, n=120)
        print(f"  {label:<8} 易图连战{easy_run*100:5.1f}% 中图连战{mid_run*100:5.1f}%"
              f" 难图连战{hard_run*100:5.1f}%  折算修为/精力 易{easy_eff:6.1f} 中{mid_eff:6.1f}")
    for stage, map_key in ((0, "太初雾泽"), (0, "虚空裂海"), (0, "混沌古狱"),
                           (1, "虚空裂海"), (2, "混沌古狱")):
        run = map_run_winrate(5, stage, map_key, profile=LIANXU_HUASHEN_GEARED, n=120)
        boss = winrate(5, stage, MAPS[map_key]["boss"], profile=LIANXU_HUASHEN_GEARED, n=120)
        print(f"  炼虚{stage}阶+化神装 {map_key:<5} 连战{run*100:5.1f}% Boss{boss*100:5.1f}%")
    prog = lianxu_progression_profile()
    ordinary = prog["ordinary"]["total_days"]
    high = prog["high"]["total_days"]
    maximum = prog["maximum"]["total_days"]
    supply = prog["stamina_supply"]
    print(f"  推进时长 普通活跃≈{ordinary:4.1f}天({ordinary/7:4.1f}周)"
          f" 高活跃≈{high:4.1f}天({high/7:4.1f}周)"
          f" 理论满勤≈{maximum:4.1f}天({maximum/7:4.1f}周)")
    print(f"  日精力供给 一管+日活{supply['one_session']}"
          f" 两管+日活{supply['two_sessions']} 理论满恢复+日活{supply['maximum']}")
    first = lianxu_first_breakthrough_profile()
    print(f"  首破周期 首丹≈{first['first_pill_days']:4.1f}天"
          f" 期望消耗{first['expected_attempts']:4.2f}枚 入炼虚≈{first['entry_days']:4.1f}天"
          f" 来源化神可及={'是' if first['huashen_accessible'] else '否'}")
    econ = m0_lianxu_economy_profiles()
    stored = econ["stored_lianxu"]
    new = econ["new_huashen"]
    print(f"  经济两档 存量炼虚图最高{stored['max_value']:5.1f}/{stored['value_cap']:5.1f}"
          f" 新进化神路线{new['route_value']:5.1f}/{new['value_cap']:5.1f}"
          f" 日耗精力{new['daily_stamina']}/{new['stamina_cap']}")
    print("-" * 78)
    print("M1 炼虚装备档回归(T1.4): LIANXU_GEARED 三图/秘境/Boss")
    for stage, map_key in ((0, "太初雾泽"), (0, "虚空裂海"), (0, "混沌古狱"),
                           (1, "虚空裂海"), (2, "混沌古狱")):
        run = map_run_winrate(5, stage, map_key, profile=LIANXU_GEARED, n=120)
        boss = winrate(5, stage, MAPS[map_key]["boss"], profile=LIANXU_GEARED, n=120)
        print(f"  炼虚{stage}阶+炼虚装 {map_key:<5} 连战{run*100:5.1f}% Boss{boss*100:5.1f}%")
    xukong_entry = dungeon_clear_fraction(5, 0, "xukong", profile=LIANXU_GEARED, n=120)
    xukong_full = dungeon_clear_fraction(5, R.num_stages(5) - 1, "xukong", profile=LIANXU_GEARED, n=120)
    lianxu_boss = world_boss_kill_challenges("lianxu", 5, 2, n=120, profile=LIANXU_GEARED)
    print(f"  虚空神殿 入门{xukong_entry*100:5.1f}% 圆满{xukong_full*100:5.1f}%"
          f"  吞虚魔蟒≈{lianxu_boss:5.1f}次")
    daily = lianxu_daily_loop_profile()
    print(f"  T1.5日常闭环 精力{daily['daily_stamina']}/{daily['stamina_cap']}"
          f" 可重复最高{daily['max_repeatable_value']:5.1f}/{daily['value_cap']:5.1f}"
          f" Boss折算{daily['boss_value']:5.1f}")
    natal_sink = natal_feed_sink_profile()
    lianxu_sink = "、".join(
        f"{key}×{qty}" for key, qty in natal_sink["lianxu_items"].items() if qty)
    print("-" * 78)
    print("M5 本命法宝喂养 sink: 2-10级材料消耗与炼虚来源覆盖")
    print(f"  标准喂养 灵石{natal_sink['standard_stone']} 器魂{natal_sink['standard_items'].get('器魂', 0)}"
          f" 炼虚材料 {lianxu_sink}")
    print(f"  器修降耗 灵石-{natal_sink['forge_stone_discount']}"
          f" 器魂-{natal_sink['forge_qihun_discount']}"
          f" 来源覆盖{'✅' if natal_sink['all_lianxu_sources_available'] else '⚠️'}")
    print("=" * 78)
    print("世界 Boss 单次伤害 & 击杀所需挑战次数(满配)")
    for bkey, cfg in WORLD_BOSSES.items():
        r = cfg["realm"]
        typ = min(2, R.num_stages(r) - 1)   # 典型参与者=后期
        dmg = boss_damage_per_challenge(r, typ, bkey)
        total = cfg["total_hp"]
        print(f"  {cfg['name']:<10} 档位r{r} total_hp{total:>7} 假人hp{cfg['combat']['hp']:>8} "
              f"  后期伤/次≈{dmg:8.0f}  击杀≈{total/dmg:5.1f}次(目标20-80)")
    print("=" * 78)
    print("经济套利:  首买精力成本/精力  vs  最佳内容产出/精力   (成本>产出 即套利已堵)")
    from services import shop
    for r in range(len(R.REALM_NAMES)):
        best = best_content_stone_per_stamina(r)
        cost_per = shop.first_buy_cost_per_stamina(r) if hasattr(
            shop, "first_buy_cost_per_stamina") else (
            shop.STAMINA_STONE_COST / shop.STAMINA_STONE_GAIN)
        flag = "  ✅堵住" if cost_per > best else "  ⚠️套利"
        print(f"  {R.REALM_NAMES[r]:<6} 最佳内容 {best:6.1f} 灵石/精力   "
              f"首买成本 {cost_per:6.1f} 灵石/精力{flag}")
    print("=" * 78)
    print("新增产出反套利(M3/M4/M5, DoD #3):含掉落变现的最佳内容 vs 首买成本")
    for r in range(len(R.REALM_NAMES)):
        best = best_content_value_per_stamina(r)
        cost_per = shop.first_buy_cost_per_stamina(r)
        flag = "  ✅堵住" if cost_per > best else "  ⚠️套利"
        print(f"  {R.REALM_NAMES[r]:<6} 含掉落最佳 {best:6.1f} 灵石/精力   "
              f"首买成本 {cost_per:6.1f} 灵石/精力{flag}")
    print(f"  白名单材料估值: {WHITELIST_MARKET_VALUE_MULTIPLIER:.0f}倍NPC回收价 "
          f"{sorted(AUCTION_WHITELIST_MATERIALS)}")
    for r in AUCTION_WHITELIST_REALMS:
        best = best_content_market_value_per_stamina(r)
        cost_per = shop.first_buy_cost_per_stamina(r)
        cap = cost_per * 0.75
        flag = "  ✅堵住" if best < cap else "  ⚠️越线"
        print(f"  {R.REALM_NAMES[r]:<6} 白名单折算 {best:6.1f} 灵石/精力   "
              f"75%红线 {cap:6.1f}{flag}")
    act = activity_daohang_profile()
    print(f"  活动道行限流: 周上限{act['weekly_cap']} 单次{act['per_run']}/精力{act['stamina_per_run']} "
          f"满档需{act['runs_to_cap']}次 {'✅有上限' if act['capped'] else '⚠️无上限'}")
    reg = regular_daohang_profile()
    print(f"  常规道行限流: 元婴起 周上限{reg['weekly_cap']} "
          f"历练单次≤{reg['max_explore']} 秘境单次≤{reg['max_dungeon']} "
          f"{'✅低于活动上限' if reg['under_activity_cap'] else '⚠️高于活动上限'}")
    asc = ascension_arbitrage_guard()
    print(f"  飞升点护栏: 每{asc['overflow_cultivation_per_point']}溢出修为凝1点 "
          f"周上限{asc['overflow_weekly_cap']} "
          f"被动上限{asc['passive_cap']}级(+{asc['max_single_pct']*100:.0f}%) "
          f"{'✅受clamp' if asc['within_clamp'] else '⚠️破clamp'} "
          f"可交易违规{asc['tradeable_violations'] or '无'}")
    print(f"  坊市护栏: 关键材料直售违规 {market_arbitrage_violations() or '无'}")


if __name__ == "__main__":
    report()
