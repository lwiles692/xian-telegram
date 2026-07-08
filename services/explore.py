from __future__ import annotations

"""历练：开始耗精力 → 按地图时长等待 → 结算战斗与掉落。"""

import random
import time

from config import daohang as DAOHANG
from config.events import ENCOUNTER_RATE, ENCOUNTERS
from config.maps import MAPS
from config.realms import realm_label
from models import db
from services import activity, character, game_events, sect_war, settle
from services.combat import Combatant, simulate

# 历练时长与遭遇密度按难度绑定（#20）：开局即定遭遇计划与时长，结算复用。
# enc=(最少, 最多) 场遭遇；minutes=(下限, 上限) 时长区间。
DIFFICULTY_PLAN = {
    "易": {"enc": (1, 1), "minutes": (8, 10)},
    "中": {"enc": (1, 2), "minutes": (10, 13)},
    "难": {"enc": (2, 3), "minutes": (13, 16)},
}
SWEEP_UNLOCK_WINS = 3
RARE_DROP_KEYS = {"筑基丹", "金丹", "元婴丹", "天材地宝", "阴风石", "幽冥草",
                  "白骨精华", "腐泽妖核", "雷纹玄铁", "劫火残晶", "天魔残页", "古战魂晶",
                  "雾泽虚砂", "裂海空髓", "混沌残核"}


def _plan_minutes(m, is_boss: bool, n_enc: int) -> float:
    plan = DIFFICULTY_PLAN.get(m.get("difficulty", "易"), DIFFICULTY_PLAN["易"])
    lo, hi = m.get("minutes", plan["minutes"])
    elo, ehi = plan["enc"]
    if is_boss:
        return hi                       # 妖王战耗时最长
    if ehi == elo:
        return (lo + hi) / 2
    return lo + (hi - lo) * (n_enc - elo) / (ehi - elo)


def _roll_plan(m, rng):
    """开局决定本次遭遇计划：是否妖王 + 遭遇场数 + 时长。"""
    plan = DIFFICULTY_PLAN.get(m.get("difficulty", "易"), DIFFICULTY_PLAN["易"])
    is_boss = rng.random() < m["boss_rate"]
    n_enc = 1 if is_boss else rng.randint(*plan["enc"])
    seconds = int(_plan_minutes(m, is_boss, n_enc) * 60)
    return is_boss, n_enc, seconds


def _roll_event(rng):
    if rng.random() >= ENCOUNTER_RATE:
        return None
    keys = list(ENCOUNTERS)
    if hasattr(rng, "choice"):
        return rng.choice(keys)
    return keys[rng.randint(0, len(keys) - 1)]


def _roll_drops(m, rng, drop_bonus: float = 0.0) -> dict:
    drops = {}
    for key, weight, qmin, qmax in m["drops"]:
        if rng.random() < min(100.0, weight * (1 + drop_bonus)) / 100.0:
            drops[key] = drops.get(key, 0) + rng.randint(qmin, qmax)
    return drops


def _regular_daohang_reward(m: dict, is_boss: bool) -> int:
    base = DAOHANG.EXPLORE_DAOHANG_BY_DIFFICULTY.get(m.get("difficulty", "易"), 0)
    return base + (DAOHANG.EXPLORE_BOSS_BONUS if is_boss else 0)


def _combatant_from_mob(src) -> Combatant:
    return Combatant(name=src["name"], hp=src["hp"], mp=src["mp"], atk=src["atk"],
                     df=src["df"], spd=src["spd"], crit=src["crit"], skills=list(src["skills"]))


def _uniform(rng, low: float, high: float) -> float:
    if hasattr(rng, "uniform"):
        return rng.uniform(low, high)
    return low + (high - low) * rng.random()


def _run_status(row, now: int) -> dict:
    m = MAPS.get(row["map_key"], {})
    remaining = max(0, row["finish_at"] - now)
    return {
        "status": "ready" if remaining == 0 else "pending",
        "map_key": row["map_key"],
        "map": m.get("name", row["map_key"]),
        "start_at": row["start_at"],
        "finish_at": row["finish_at"],
        "remaining": remaining,
    }


def _event_status(row) -> dict:
    event = ENCOUNTERS.get(row["event_key"], {})
    choices = [
        {"key": key, "label": choice["label"]}
        for key, choice in (event.get("choices") or {}).items()
    ]
    m = MAPS.get(row["map_key"], {})
    return {
        "status": "event",
        "map_key": row["map_key"],
        "map": m.get("name", row["map_key"]),
        "event_key": row["event_key"],
        "title": event.get("title", "奇遇"),
        "text": event.get("text", "前路忽生变数。"),
        "choices": choices,
    }


def _event_effect(event_key: str, choice_key: str) -> dict:
    event = ENCOUNTERS.get(event_key, {})
    return dict((event.get("choices") or {}).get(choice_key) or {})


async def mastery(user_id: int, map_key: str) -> dict:
    row = await db.fetchone(
        "SELECT * FROM explore_mastery WHERE user_id=? AND map_key=?",
        (user_id, map_key))
    return dict(row) if row else {"user_id": user_id, "map_key": map_key,
                                  "consecutive_wins": 0, "last_result_at": 0}


async def _record_mastery_conn(conn, user_id: int, map_key: str, win: bool, now: int):
    if win:
        await conn.execute(
            "INSERT INTO explore_mastery(user_id, map_key, consecutive_wins, last_result_at) "
            "VALUES(?,?,1,?) "
            "ON CONFLICT(user_id, map_key) DO UPDATE SET "
            "consecutive_wins=consecutive_wins+1, last_result_at=?",
            (user_id, map_key, now, now))
    else:
        await conn.execute(
            "INSERT INTO explore_mastery(user_id, map_key, consecutive_wins, last_result_at) "
            "VALUES(?,?,0,?) "
            "ON CONFLICT(user_id, map_key) DO UPDATE SET consecutive_wins=0, last_result_at=?",
            (user_id, map_key, now, now))


async def can_sweep(user_id: int, map_key: str, conn=None) -> bool:
    m = MAPS.get(map_key)
    if not m:
        return False
    sql = "SELECT realm FROM characters WHERE user_id=?"
    if conn is not None:
        cur = await conn.execute(sql, (user_id,))
        char = await cur.fetchone()
        await cur.close()
        cur = await conn.execute(
            "SELECT consecutive_wins FROM explore_mastery WHERE user_id=? AND map_key=?",
            (user_id, map_key))
        row = await cur.fetchone()
        await cur.close()
    else:
        char = await db.fetchone(sql, (user_id,))
        row = await db.fetchone(
            "SELECT consecutive_wins FROM explore_mastery WHERE user_id=? AND map_key=?",
            (user_id, map_key))
    return bool(char and char["realm"] == m["realm"]
                and row and row["consecutive_wins"] >= SWEEP_UNLOCK_WINS)


async def active_run(user_id: int, now: int = None):
    now = int(time.time()) if now is None else now
    row = await db.fetchone(
        "SELECT * FROM explore_runs WHERE user_id=? AND status='active'",
        (user_id,))
    return _run_status(row, now) if row else None


async def start(user_id: int, map_key: str, now: int = None, rng=None) -> dict:
    now = int(time.time()) if now is None else now
    m = MAPS.get(map_key)
    if not m:
        return {"status": "bad_map"}
    rng = rng or random.Random(f"{user_id}:{map_key}:{now}")
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT * FROM explore_runs WHERE user_id=? AND status='active'",
            (user_id,))
        active = await cur.fetchone()
        await cur.close()
        if active:
            return _run_status(active, now)

        cur = await conn.execute(
            "SELECT 1 FROM dungeon_jobs WHERE user_id=? AND status='active'",
            (user_id,))
        busy = await cur.fetchone()
        await cur.close()
        if busy:
            return {"status": "busy_dungeon"}

        row = await character._select_character(conn, user_id)
        if not row:
            return {"status": "missing"}
        if row["realm"] < m["realm"]:
            return {"status": "locked", "need": realm_label(m["realm"], 0)}
        welfare = await character._sect_welfare(conn, user_id)
        stamina, stamina_at = character._settled_stamina(row, now, welfare)
        cost = m["stamina"]
        if stamina < cost:
            await conn.execute(
                "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
                (stamina, stamina_at, user_id))
            return {"status": "no_stamina", "need": cost, "have": stamina}
        # 开局即定遭遇计划与时长，并落库；结算阶段复用，使时长与战斗数量不脱钩（#20）。
        is_boss, n_enc, seconds = _roll_plan(m, rng)
        event_key = _roll_event(rng)
        event_seed = rng.randint(1, 10_000_000) if event_key else None
        finish_at = now + seconds
        seed = rng.randint(1, 10_000_000)
        await conn.execute(
            "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
            (stamina - cost, stamina_at, user_id))
        # 快照出发血蓝（结算到出发时刻），战斗按此开打，不被晚领/中途嗑丹绕过（#24 P1）。
        char_obj = character._from_row(row)
        sst = await character.stats(char_obj)
        start_hp, _, start_mp, _ = character.settled_vitals(char_obj, sst["hp"], sst["mp"], now)
        # 冻结当前血蓝：锚点设 finish_at，活动期间不自然回复（回来才休整）；结算时按"当前-战斗损耗"合并。
        await character.write_vitals(user_id, start_hp, start_mp, finish_at, conn=conn)
        await conn.execute(
            "INSERT INTO explore_runs(user_id, map_key, start_at, finish_at, seed, status, "
            "encounters, is_boss, start_hp, start_mp, event_key, event_seed) "
            "VALUES(?,?,?,?,?,'active',?,?,?,?,?,?)",
            (user_id, map_key, now, finish_at, seed, n_enc, 1 if is_boss else 0,
             start_hp, start_mp, event_key, event_seed))
        await activity.record_window(user_id, "explore", map_key, now, finish_at, conn=conn)
        return {
            "status": "started",
            "map_key": map_key,
            "map": m["name"],
            "difficulty": m.get("difficulty", "易"),
            "finish_at": finish_at,
            "seconds": finish_at - now,
            "encounters": n_enc,
            "event": event_key,
            "stamina_left": stamina - cost,
        }


async def collect(user_id: int, now: int = None, rng=None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT * FROM explore_runs WHERE user_id=? AND status='active'",
            (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return {"status": "no_active"}
        if row["finish_at"] > now:
            return _run_status(row, now)
        if row["event_key"] and not row["event_choice"]:
            return _event_status(row)
        # 在同一事务内结算并删除，避免"已删但奖励未发"的崩溃窗口。
        # 旧库在途历练的 encounters/is_boss 为 NULL，传 None 触发 _resolve 的兼容分支。
        stored_boss = row["is_boss"]
        result = await _resolve(
            user_id, row["map_key"], row["seed"], now, rng, conn=conn,
            n_enc=row["encounters"],
            is_boss=None if stored_boss is None else bool(stored_boss),
            start_hp=row["start_hp"], start_mp=row["start_mp"], finish_at=row["finish_at"])
        if result["status"] == "ok":
            await _record_mastery_conn(conn, user_id, row["map_key"], bool(result["win"]), now)
        await conn.execute("DELETE FROM explore_runs WHERE user_id=?", (user_id,))
        return result


async def choose_event(user_id: int, choice_key: str, now: int = None, rng=None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT * FROM explore_runs WHERE user_id=? AND status='active'",
            (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return {"status": "no_active"}
        if row["finish_at"] > now:
            return _run_status(row, now)
        if not row["event_key"]:
            return {"status": "no_event"}
        event = ENCOUNTERS.get(row["event_key"], {})
        if choice_key not in (event.get("choices") or {}):
            return {"status": "bad_choice"}
        stored_boss = row["is_boss"]
        await conn.execute(
            "UPDATE explore_runs SET event_choice=? WHERE user_id=?",
            (choice_key, user_id))
        result = await _resolve(
            user_id, row["map_key"], row["seed"], now, rng, conn=conn,
            n_enc=row["encounters"],
            is_boss=None if stored_boss is None else bool(stored_boss),
            start_hp=row["start_hp"], start_mp=row["start_mp"], finish_at=row["finish_at"],
            event_effect=_event_effect(row["event_key"], choice_key),
            mode="event")
        if result["status"] == "ok":
            await _record_mastery_conn(conn, user_id, row["map_key"], bool(result["win"]), now)
        await conn.execute("DELETE FROM explore_runs WHERE user_id=?", (user_id,))
        return result


async def sweep(user_id: int, map_key: str, now: int = None, rng=None) -> dict:
    now = int(time.time()) if now is None else now
    m = MAPS.get(map_key)
    if not m:
        return {"status": "bad_map"}
    rng = rng or random.Random(f"sweep:{user_id}:{map_key}:{now}")
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM explore_runs WHERE user_id=? AND status='active'",
            (user_id,))
        active = await cur.fetchone()
        await cur.close()
        if active:
            return {"status": "busy_explore"}
        cur = await conn.execute(
            "SELECT 1 FROM dungeon_jobs WHERE user_id=? AND status='active'",
            (user_id,))
        busy = await cur.fetchone()
        await cur.close()
        if busy:
            return {"status": "busy_dungeon"}
        row = await character._select_character(conn, user_id)
        if not row:
            return {"status": "missing"}
        if row["realm"] < m["realm"]:
            return {"status": "locked", "need": realm_label(m["realm"], 0)}
        if not await can_sweep(user_id, map_key, conn=conn):
            return {"status": "sweep_locked", "need": SWEEP_UNLOCK_WINS}
        welfare = await character._sect_welfare(conn, user_id)
        stamina, stamina_at = character._settled_stamina(row, now, welfare)
        cost = m["stamina"]
        if stamina < cost:
            await conn.execute(
                "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
                (stamina, stamina_at, user_id))
            return {"status": "no_stamina", "need": cost, "have": stamina}
        is_boss, n_enc, seconds = _roll_plan(m, rng)
        seed = rng.randint(1, 10_000_000)
        char_obj = character._from_row(row)
        sst = await character.stats(char_obj)
        start_hp, _, start_mp, _ = character.settled_vitals(char_obj, sst["hp"], sst["mp"], now)
        await conn.execute(
            "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
            (stamina - cost, stamina_at, user_id))
        await character.write_vitals(user_id, start_hp, start_mp, now, conn=conn)
        await activity.record_virtual_window(user_id, "sweep", map_key, now, seconds, conn=conn)
        result = await _resolve(
            user_id, map_key, seed, now, rng, conn=conn,
            n_enc=n_enc, is_boss=is_boss,
            start_hp=start_hp, start_mp=start_mp, finish_at=now,
            mode="sweep")
        if result["status"] == "ok":
            result["sweep"] = True
            await _record_mastery_conn(conn, user_id, map_key, bool(result["win"]), now)
        return result


async def explore(user_id: int, map_key: str, rng=None, now: int = None) -> dict:
    return await start(user_id, map_key, now, rng)


async def _resolve(user_id: int, map_key: str, seed: int, now: int, rng=None, conn=None,
                   n_enc: int = None, is_boss: bool = None,
                   start_hp: int = None, start_mp: int = None, finish_at: int = None,
                   event_effect: dict = None, mode: str = "explore") -> dict:
    m = MAPS.get(map_key)
    if not m:
        return {"status": "bad_map"}
    rng = rng or random.Random(seed)
    if conn is not None:
        # 已在写事务内：只读取角色（不触发 get_at 的精力落库写，避免重入写锁死锁）。
        row = await character._select_character(conn, user_id)
        char = character._from_row(row) if row else None
    else:
        char = await character.get_at(user_id, now)
    if not char:
        return {"status": "missing"}
    st = await character.stats(char)
    skills = await character.get_skills(user_id)
    mods = await character.combat_mods(user_id)
    max_hp, max_mp = st["hp"], st["mp"]
    # 战前用「出发时」快照血蓝开打（#24 P1）：晚领/中途嗑丹都不影响本场；旧在途 run 无快照→满血。
    if start_hp is None:
        cur_hp, cur_mp = max_hp, max_mp
    else:
        cur_hp = max(0, min(start_hp, max_hp))
        cur_mp = max(0, min(start_mp, max_mp))
    event_effect = event_effect or {}
    event_logs = []
    if event_effect:
        event_logs.append(event_effect.get("text", "奇遇已择。"))
        hazard = int(max_hp * float(event_effect.get("hazard_hp_pct", 0.0) or 0.0))
        if hazard > 0:
            cur_hp = max(1, cur_hp - hazard)
            event_logs.append(f"洞府机关暗发，先损气血 {hazard}。")
    player = Combatant(name="道友", hp=cur_hp, mp=cur_mp, max_hp=max_hp, max_mp=max_mp,
                       atk=st["atk"], df=st["df"], spd=st["spd"], crit=st["crit"],
                       skills=skills or ["普攻"], **mods)
    if is_boss is None:
        # 兼容无存储计划的旧 run：即时 roll 一份计划。
        is_boss = rng.random() < m["boss_rate"]
        n_enc = 1 if is_boss else rng.randint(1, 3)
    mob_sources = ([m["boss"]] if is_boss
                   else [rng.choice(m["mobs"]) for _ in range(max(1, n_enc or 1))])
    logs = list(event_logs)
    win = True
    defeat_reason = None
    for idx, mob_src in enumerate(mob_sources, 1):
        result = simulate(
            player, _combatant_from_mob(mob_src),
            seed=rng.randint(1, 10_000_000), max_rounds=None)
        logs.append(f"第 {idx} 战：遭遇 {mob_src['name']}")
        shown = result["log"] if len(result["log"]) <= 5 else (result["log"][:4] + ["……", result["log"][-1]])
        logs.extend(shown[1:])
        if result["winner"] is not player:
            win = False
            defeat_reason = result.get("reason")
            break
        player.hp = max(1, result["a_hp"])

    reward = {"stone": 0, "cult": 0, "drops": {}, "daohang": 0}
    if win:
        mult = 2 if is_boss else 1
        reward_mult = float(event_effect.get("reward_mult", 1.0) or 1.0)
        stone = int(rng.randint(*m["stone"]) * mult * reward_mult)
        cult = max(1, int(m["cult"] * _uniform(rng, 0.9, 1.1) * reward_mult)) * mult
        welfare = await character.sect_welfare(user_id)
        outpost = await sect_war.bonuses_for_user(user_id)
        drop_pct = sect_war.total_drop_pct(welfare["drop_pct"], outpost)
        drops = _roll_drops(m, rng, drop_pct + float(event_effect.get("drop_bonus", 0.0) or 0.0))
        daohang = 0
        if conn is not None:
            await character._grant_reward_conn(conn, user_id, stone, cult, drops)
            daohang = await character.grant_regular_daohang_conn(
                conn, user_id, _regular_daohang_reward(m, is_boss),
                "explore_regular", now, realm=char.realm)
            contribution = int(event_effect.get("contribution", 0) or 0)
            if contribution:
                await conn.execute(
                    "UPDATE sect_members SET contribution=contribution+? WHERE user_id=?",
                    (contribution, user_id))
        else:
            await character.grant_reward(user_id, stone, cult, drops)
            daohang = await character.grant_regular_daohang(
                user_id, _regular_daohang_reward(m, is_boss),
                "explore_regular", now, realm=char.realm)
        reward = {"stone": stone, "cult": cult, "drops": drops, "daohang": daohang}

    # 严格事件顺序（#24 P1）：先得「战斗结束状态」(finish_at，落 20% 重伤地板)，
    # 再从该状态自然回复到领取时刻 now。领取前已禁服恢复丹，故无需合并。
    anchor = finish_at if finish_at is not None else now
    combat_hp = character.floor_hp(max_hp, player.hp)
    combat_mp = max(0, min(player.mp, max_mp))
    final_hp, _ = settle.regen_resource(combat_hp, max_hp, anchor, now, settle.HP_REGEN_SECONDS_PER_FULL)
    final_mp, _ = settle.regen_resource(combat_mp, max_mp, anchor, now, settle.MP_REGEN_SECONDS_PER_FULL)
    await character.write_vitals(user_id, final_hp, final_mp, now, conn=conn)
    if conn is not None and win:
        payload = {
            "map_key": map_key,
            "map": m["name"],
            "mode": mode,
            "is_boss": is_boss,
            "mob": "、".join(src["name"] for src in mob_sources),
            "drops": reward["drops"],
            "amount": 1,
        }
        await game_events.emit_conn(conn, user_id, "explore.win", payload, now)
        if is_boss:
            await game_events.emit_conn(conn, user_id, "explore.boss_win", payload, now)
        rare = {k: v for k, v in reward["drops"].items() if k in RARE_DROP_KEYS}
        if rare:
            await game_events.emit_conn(conn, user_id, "explore.rare_drop", {**payload, "drops": rare}, now)

    return {"status": "ok", "map_key": map_key, "map": m["name"],
            "win": win, "is_boss": is_boss,
            "defeat_reason": defeat_reason,
            "mob": "、".join(src["name"] for src in mob_sources),
            "log": logs, "reward": reward, "stamina_left": char.stamina,
            # 战斗快照（出发→战斗末，解释胜负）与领取后当前状态（落库）分开展示（#24 P2）。
            "battle_hp_before": cur_hp, "battle_hp_after": max(0, player.hp),
            "battle_mp_before": cur_mp, "battle_mp_after": max(0, player.mp),
            "hp_after": final_hp, "mp_after": final_mp,
            "max_hp": max_hp, "max_mp": max_mp}
