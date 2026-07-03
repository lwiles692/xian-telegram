"""平衡 / 经济模拟器（issues #13-#16 的共同地基）。

纯函数,基于 ``services.combat.simulate``,不碰 DB。玩家属性按
``services.character.stats`` 的同样顺序构造(装备平加 → 心法乘算)。
固定 seed=0..N-1,胜率是确定值,可直接做回归断言。

直接运行打印报告::

    python -m tools.balance_sim
"""
from __future__ import annotations

import random

from config import realms as R
from config import buffs as BUFFS
from config import dao_paths as DAO
from config.ascension import PASSIVE_CAP
from config.bosses import WORLD_BOSSES
from config.dungeons import DUNGEONS
from config.items import ITEMS
from config.maps import MAPS
from config.shop import SHOP_ITEMS
from config.skills import SKILLS
from config.weekly_events import (RUN_DAOHANG_REWARD, RUN_STAMINA_COST, WEEKLY_DAOHANG_CAP)
from services.combat import Combatant, simulate

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
# 元婴圆满满 buff 上界档：现役元婴装备 + 可叠满临时/福利 buff（推到 §6.3 合算上限）。
# 红线护栏（spec §3.2）：即便如此仍不得稳定刷化神中/难 Boss。M0 阶段不含道途。
YUANYING_FULL_BUFF = {
    **YUANYING_TREASURE_GEARED,
    "extra_pct": {"atk": BUFFS.ATTACK_PCT_CAP, "crit": BUFFS.ATTACK_PCT_CAP,
                  "hp": BUFFS.SURVIVAL_PCT_CAP, "df": BUFFS.SURVIVAL_PCT_CAP},
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
CONTENT_REALM = {"后山": 0, "妖兽森林": 1, "万妖岭": 2, "上古战场": 3, "星陨海": 4}


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
    return 1.0 + min(BUFFS.SECLUSION_PCT_CAP, max(0.0, float(bonus.get("seclusion_pct", 0))))


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

def _drops_sell_expectation(drops) -> float:
    """drops [(key, weight, qmin, qmax)] 的单次期望 sell 价值。

    复刻 explore._roll_drops：weight/100 为掉率，数量 randint(qmin,qmax) 取均值。
    绑定材料 sell=0 自然不计入（不构成可变现产出）。
    """
    total = 0.0
    for key, weight, qmin, qmax in drops:
        chance = min(100.0, float(weight)) / 100.0
        sell = float(ITEMS.get(key, {}).get("sell", 0) or 0)
        total += chance * (qmin + qmax) / 2 * sell
    return total


def map_drops_sell_per_stamina(map_key: str) -> float:
    return _drops_sell_expectation(MAPS[map_key]["drops"]) / MAPS[map_key]["stamina"]


def dungeon_drops_sell_per_stamina(dungeon_key: str) -> float:
    """秘境掉落 sell/精力：drops 不受 reward_factor 放大（复刻 _resolve：仅 stone/cult 放大）。"""
    d = DUNGEONS[dungeon_key]
    return _drops_sell_expectation(d["drops"]) / d["stamina"]


def best_content_value_per_stamina(realm: int) -> float:
    """含掉落变现(灵石+可回收物)的最佳内容产出/精力。反套利红线须 < 首买成本/精力。"""
    vals = [map_stone_per_stamina(k) + map_drops_sell_per_stamina(k)
            for k, m in MAPS.items() if m["realm"] <= realm]
    vals += [dungeon_stone_per_stamina(k) + dungeon_drops_sell_per_stamina(k)
             for k, d in DUNGEONS.items() if d["realm"] <= realm]
    return max(vals) if vals else 0.0


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


# 飞升点为账号级数值，非物品（不在 ITEMS/SHOP，天然不可交易）。
_ASCENSION_TRADEABLE_KEYS = ("飞升点",)


def ascension_arbitrage_guard() -> dict:
    """飞升点(M3)反套利：被动增益受 PASSIVE_CAP 硬上限 + §6.3 clamp 双约束。"""
    max_single_pct = PASSIVE_CAP * 0.01
    return {
        "passive_cap": PASSIVE_CAP,
        "max_single_pct": max_single_pct,
        "within_clamp": max_single_pct <= min(BUFFS.ATTACK_PCT_CAP, BUFFS.SURVIVAL_PCT_CAP),
        "tradeable_violations": [k for k in _ASCENSION_TRADEABLE_KEYS
                                 if k in ITEMS or k in SHOP_ITEMS],
    }


# 坊市套利护栏：关键成长材料不得进 NPC 直售（否则内容门槛被灵石绕过）。
_MARKET_BANNED_FROM_SHOP = ("化神丹", "化神丹方", "化神丹残方", "转修令")


def market_arbitrage_violations() -> list[str]:
    """关键突破丹/飞升链材料不得在 NPC 直售；运行时 market 仅放行 bound=0（绑定不可上架）。"""
    return [k for k in _MARKET_BANNED_FROM_SHOP if k in SHOP_ITEMS]


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
        profile = HUASHEN_GEARED if r == 4 else GEARED
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
    act = activity_daohang_profile()
    print(f"  活动道行限流: 周上限{act['weekly_cap']} 单次{act['per_run']}/精力{act['stamina_per_run']} "
          f"满档需{act['runs_to_cap']}次 {'✅有上限' if act['capped'] else '⚠️无上限'}")
    asc = ascension_arbitrage_guard()
    print(f"  飞升点护栏: 被动上限{asc['passive_cap']}级(+{asc['max_single_pct']*100:.0f}%) "
          f"{'✅受clamp' if asc['within_clamp'] else '⚠️破clamp'} "
          f"可交易违规{asc['tradeable_violations'] or '无'}")
    print(f"  坊市护栏: 关键材料直售违规 {market_arbitrage_violations() or '无'}")


if __name__ == "__main__":
    report()
