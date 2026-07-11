from __future__ import annotations

"""突破：小突破自动；大突破需突破丹 + 成功率（金丹起渡天劫）。

失败=损失部分当前修为、**不跌境**（spec §4.3，轻惩罚）。
"""

import json
import random
import time

from config.events import (
    HEART_TRIBULATION_BUFF_DURATION,
    HEART_TRIBULATION_BUFF_KEY,
    HEART_TRIBULATION_BUFF_NAME,
    HEART_TRIBULATION_ACTION_KEY,
    HEART_TRIBULATION_DAOHANG,
    HEART_TRIBULATION_FAIL_EXTRA_LOSS_PCT,
    HEART_TRIBULATION_REWARD_FLAG,
    HEART_TRIBULATION_SECLUSION_PCT,
    SHENHUN_TRIBULATION_ACTIONS,
    TRIBULATION_ACTIONS,
    XUKONG_TRIBULATION_ACTIONS,
)
from config.items import ITEMS
from config.realms import (BIG_BREAKTHROUGH, advance_cost, is_big_breakthrough,
                           next_stage, realm_label, base_stats)
from models import db
from services import bonds as bonds_service
from services import game_events
from services import character as character_service
from services import dao_path

FAIL_CULT_LOSS = 0.30
UNSTABLE_SECONDS = 6 * 3600
LIANXU_TARGET_REALM = 5
BIG_FAIL_GUARANTEE_STEP = 0.10
HEART_SUCCESS_EVENT = "breakthrough.heart_success"
HEART_FAIL_EVENT = "breakthrough.heart_fail"


def big_success_rate(realm: int, root_bone: int, pill_bonus: float = 0.0) -> float:
    """跨入 realm+1 大境界的成功率，受根骨/丹药修正，限 [0.05, 0.95]。"""
    base = BIG_BREAKTHROUGH[realm + 1]["base_rate"]
    rate = base + (root_bone - 50) * 0.003 + pill_bonus
    return max(0.05, min(0.95, rate))


def _lianxu_guarantee_bonus(target_realm: int, fail_streak: int) -> float:
    if target_realm != LIANXU_TARGET_REALM:
        return 0.0
    return max(0, int(fail_streak or 0)) * BIG_FAIL_GUARANTEE_STEP


def _apply_guarantee(rate: float, guarantee_bonus: float) -> float:
    return max(0.05, min(0.95, rate + guarantee_bonus))


async def _record_big_failure(conn, user_id: int, target_realm: int):
    if target_realm == LIANXU_TARGET_REALM:
        await conn.execute(
            "UPDATE characters SET big_fail_streak=big_fail_streak+1 WHERE user_id=?",
            (user_id,))


async def _clear_big_fail_streak(conn, user_id: int, target_realm: int):
    if target_realm == LIANXU_TARGET_REALM:
        await conn.execute(
            "UPDATE characters SET big_fail_streak=0 WHERE user_id=?",
            (user_id,))


def _is_heart_reward(reward_flag: str | None) -> bool:
    return reward_flag == HEART_TRIBULATION_REWARD_FLAG


def _with_heart_buff(state_json: str, now: int) -> dict:
    state = json.loads(state_json or "{}")
    state.pop("unstable_until", None)
    buffs = state.setdefault("buffs", {})
    buffs[HEART_TRIBULATION_BUFF_KEY] = {
        "until": now + HEART_TRIBULATION_BUFF_DURATION,
        "name": HEART_TRIBULATION_BUFF_NAME,
        "effects": {"seclusion_pct": HEART_TRIBULATION_SECLUSION_PCT},
    }
    return state


async def _grant_heart_daohang_conn(conn, user_id: int, now: int) -> int:
    amount = int(HEART_TRIBULATION_DAOHANG)
    if amount <= 0:
        return 0
    await conn.execute(
        "UPDATE characters SET daohang=daohang+? WHERE user_id=?",
        (amount, user_id))
    await conn.execute(
        "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
        "VALUES(?,NULL,?,?,?)",
        (user_id, "heart_tribulation", amount, now))
    return amount


def tribulation_trial(source_realm: int, source_stage: int, root_bone: int,
                      guard_bonus: int = 0, rng=None) -> dict:
    rng = rng or random
    stats = base_stats(source_realm, source_stage)
    hp = stats["hp"]
    shield = int(stats["df"] * 0.6 + root_bone * 2 + guard_bonus)
    log = []
    for idx in range(1, 4):
        raw = int((stats["hp"] * 0.18 + stats["df"] * 1.8) * (0.9 + rng.random() * 0.2))
        dmg = max(1, raw - shield)
        hp -= dmg
        log.append(f"第 {idx} 道雷劫落下，承伤 {dmg}")
        if hp <= 0:
            return {"survived": False, "log": log}
    return {"survived": True, "log": log}


async def _breakthrough_mods(conn, user_id: int) -> dict:
    cur = await conn.execute(
        "SELECT base_key, affixes_json FROM item_instances "
        "WHERE user_id=? AND equipped_slot IS NOT NULL",
        (user_id,))
    rows = await cur.fetchall()
    await cur.close()
    rate = 0.0
    guard = 0
    for row in rows:
        item = ITEMS.get(row["base_key"], {})
        rate += float(item.get("breakthrough_rate", 0.0))
        guard += int(item.get("tribulation_shield", 0))
    cur = await conn.execute(
        "SELECT skill_key FROM character_skills WHERE user_id=? AND slot>=0",
        (user_id,))
    skills = {row["skill_key"] for row in await cur.fetchall()}
    await cur.close()
    if "金钟罩" in skills:
        guard += 120
    return {"rate": rate, "guard": guard}


async def _fail(conn, user_id: int, cultivation: int, rate: float, trib: bool,
                loss: int = None, tribulation_log=None, now: int = None,
                target_realm: int = None, guarantee_bonus: float = 0.0,
                reward_flag: str | None = None):
    now = int(time.time()) if now is None else now
    base_loss = int(cultivation * FAIL_CULT_LOSS) if loss is None else loss
    extra_loss = 0
    if _is_heart_reward(reward_flag):
        cur = await conn.execute("SELECT cultivation FROM characters WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        current_cultivation = int(row["cultivation"] if row else cultivation)
        extra_loss = int(current_cultivation * HEART_TRIBULATION_FAIL_EXTRA_LOSS_PCT)
    loss = base_loss + extra_loss
    debuff = json.dumps({"unstable_until": now + UNSTABLE_SECONDS}, ensure_ascii=False)
    await _record_big_failure(conn, user_id, target_realm or -1)
    await conn.execute(
        "UPDATE characters SET cultivation=MAX(0, cultivation - ?), debuff_json=? WHERE user_id=?",
        (loss, debuff, user_id))
    if _is_heart_reward(reward_flag):
        await game_events.emit_conn(
            conn, user_id, HEART_FAIL_EVENT,
            {"target_realm": target_realm, "loss": loss, "extra_loss": extra_loss}, now)
    return {"status": "big_fail", "rate": rate, "tribulation": trib, "loss": loss,
            "tribulation_log": tribulation_log or [],
            "debuff_seconds": UNSTABLE_SECONDS, "guarantee_bonus": guarantee_bonus,
            "heart_reward": _is_heart_reward(reward_flag), "extra_loss": extra_loss}


def _tribulation_actions(target_realm: int) -> dict:
    if target_realm == 5:
        return XUKONG_TRIBULATION_ACTIONS
    if target_realm == 4:
        return SHENHUN_TRIBULATION_ACTIONS
    return TRIBULATION_ACTIONS


def _available_tribulation_actions(target_realm: int, thunder_index: int) -> dict:
    actions = dict(_tribulation_actions(target_realm))
    if int(thunder_index) != 3:
        actions.pop(HEART_TRIBULATION_ACTION_KEY, None)
    return actions


def _trial_name(target_realm: int) -> str:
    if target_realm == 5:
        return "虚空劫"
    if target_realm == 4:
        return "神魂劫"
    return "雷劫"


def _tribulation_choices(target_realm: int, thunder_index: int) -> list[dict]:
    actions = _available_tribulation_actions(target_realm, thunder_index)
    return [{"key": key, "label": cfg["label"]} for key, cfg in actions.items()]


def _tribulation_status(row) -> dict:
    return {"status": "tribulation_choice", "tribulation": True,
            "target_realm": row["target_realm"],
            "thunder_index": row["thunder_index"], "total": 3,
            "hp": row["hp"],
            "choices": _tribulation_choices(row["target_realm"], row["thunder_index"]),
            "rate": row["rate"], "guarantee_bonus": row["guarantee_bonus"],
            "reward_flag": row["reward_flag"],
            "tribulation_log": json.loads(row["log_json"] or "[]")}


async def _session(conn, user_id: int):
    cur = await conn.execute("SELECT * FROM tribulation_sessions WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row


async def try_advance(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM characters WHERE user_id=?", (user_id,))
        char = await cur.fetchone()
        await cur.close()
        if not char:
            return {"status": "missing"}
        active = await _session(conn, user_id)
        if active:
            return _tribulation_status(active)
        if char["seclusion_at"]:
            return {"status": "in_seclusion"}

        cost = advance_cost(char["realm"], char["stage"])
        if char["cultivation"] < cost:
            return {"status": "need_cult", "need": cost - char["cultivation"]}
        nxt = next_stage(char["realm"], char["stage"])
        if nxt is None:
            return {"status": "at_cap"}

        if is_big_breakthrough(char["realm"], char["stage"]):
            target = char["realm"] + 1
            pill = BIG_BREAKTHROUGH[target]["pill"]
            if await character_service.item_qty_conn(conn, user_id, pill) < 1:
                return {"status": "need_pill", "pill": pill}
            await character_service.consume_item_conn(conn, user_id, pill, 1)
            mods = await _breakthrough_mods(conn, user_id)
            # 丹修道途 alchemy_pct 直接加成大突破成功率（口径同 balance_sim）。
            dao_bonus = await dao_path.active_bonuses(user_id)
            pill_bonus = mods["rate"] + float(dao_bonus.get("alchemy_pct", 0.0))
            base_rate = big_success_rate(char["realm"], char["root_bone"], pill_bonus)
            guarantee_bonus = _lianxu_guarantee_bonus(target, char["big_fail_streak"])
            rate = _apply_guarantee(base_rate, guarantee_bonus)
            trib = BIG_BREAKTHROUGH[target]["tribulation"]
            if random.random() >= rate:
                return await _fail(
                    conn, user_id, char["cultivation"], rate, trib, now=now,
                    target_realm=target, guarantee_bonus=guarantee_bonus)
            tribulation = {"survived": True, "log": []}
            if trib:
                stats = base_stats(char["realm"], char["stage"])
                base_guard = int(stats["df"] * 0.6 + char["root_bone"] * 2 + mods["guard"])
                await conn.execute(
                    "INSERT OR REPLACE INTO tribulation_sessions("
                    "user_id, source_realm, source_stage, target_realm, target_stage, "
                    "cultivation, cost, rate, guarantee_bonus, guard_bonus, hp, thunder_index, seed, log_json, created_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (user_id, char["realm"], char["stage"], nxt[0], nxt[1],
                     char["cultivation"], cost, rate, guarantee_bonus, base_guard, stats["hp"], 1,
                     random.randint(1, 10_000_000), "[]", now))
                row = await _session(conn, user_id)
                return _tribulation_status(row)
            if tribulation["survived"]:
                await _clear_big_fail_streak(conn, user_id, target)
                await conn.execute(
                    "UPDATE characters SET realm=?, stage=?, cultivation=?, debuff_json='{}' "
                    "WHERE user_id=?",
                    (nxt[0], nxt[1], max(0, char["cultivation"] - cost), user_id))
                await game_events.emit_conn(
                    conn, user_id, "breakthrough.big_success",
                    {"target_realm": nxt[0], "target_stage": nxt[1],
                     "label": realm_label(nxt[0], nxt[1])}, now)
                mentor_milestone = await bonds_service.handle_disciple_breakthrough_conn(
                    conn, user_id, nxt[0], nxt[1], now)
                return {"status": "big_success", "rate": rate, "tribulation": trib,
                        "label": realm_label(nxt[0], nxt[1]),
                        "tribulation_log": tribulation["log"],
                        "pill_used": pill,
                        "guarantee_bonus": guarantee_bonus,
                        "mentor_milestone": mentor_milestone}
            return await _fail(
                conn, user_id, char["cultivation"], rate, trib,
                tribulation_log=tribulation["log"], now=now,
                target_realm=target, guarantee_bonus=guarantee_bonus)

        await conn.execute(
            "UPDATE characters SET realm=?, stage=?, cultivation=?, debuff_json='{}' WHERE user_id=?",
            (nxt[0], nxt[1], max(0, char["cultivation"] - cost), user_id))
        return {"status": "small_success", "label": realm_label(nxt[0], nxt[1])}


async def choose_tribulation_action(user_id: int, action_key: str, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        row = await _session(conn, user_id)
        if not row:
            return {"status": "no_tribulation"}
        action = _available_tribulation_actions(
            row["target_realm"], row["thunder_index"]).get(action_key)
        if not action:
            return {"status": "bad_action"}
        cur = await conn.execute("SELECT * FROM characters WHERE user_id=?", (user_id,))
        char = await cur.fetchone()
        await cur.close()
        if not char:
            return {"status": "missing"}
        item_key = action.get("item")
        if item_key:
            if await character_service.item_qty_conn(conn, user_id, item_key) < 1:
                return {"status": "need_item", "item": item_key}
            await character_service.consume_item_conn(conn, user_id, item_key, 1)

        stats = base_stats(row["source_realm"], row["source_stage"])
        max_hp = stats["hp"]
        hp = min(max_hp, int(row["hp"]) + int(max_hp * float(action.get("heal_pct", 0.0) or 0.0)))
        idx = int(row["thunder_index"])
        rng = random.Random(int(row["seed"]) + idx * 104729)
        raw = int((stats["hp"] * 0.18 + stats["df"] * 1.8) * (0.9 + rng.random() * 0.2))
        reward_flag = action.get("reward_flag")
        if action.get("ignore_guard"):
            shield = int(action.get("shield", 0) or 0)
        else:
            shield = int(row["guard_bonus"]) + int(action.get("shield", 0) or 0)
        dmg = max(1, raw - shield)
        hp -= dmg
        logs = json.loads(row["log_json"] or "[]")
        logs.append(action["text"])
        trial_name = _trial_name(row["target_realm"])
        logs.append(f"第 {idx} 道{trial_name}落下，承伤 {dmg}，余气血 {max(0, hp)}/{max_hp}")
        if hp <= 0:
            await conn.execute("DELETE FROM tribulation_sessions WHERE user_id=?", (user_id,))
            return await _fail(conn, user_id, row["cultivation"], row["rate"], True,
                               tribulation_log=logs, now=now,
                               target_realm=row["target_realm"],
                               guarantee_bonus=row["guarantee_bonus"],
                               reward_flag=reward_flag)
        if idx >= 3:
            await conn.execute("DELETE FROM tribulation_sessions WHERE user_id=?", (user_id,))
            await _clear_big_fail_streak(conn, user_id, row["target_realm"])
            heart_reward = _is_heart_reward(reward_flag)
            daohang = 0
            debuff_json = "{}"
            if heart_reward:
                debuff_json = json.dumps(_with_heart_buff(char["debuff_json"], now), ensure_ascii=False)
            await conn.execute(
                "UPDATE characters SET realm=?, stage=?, "
                "cultivation=MAX(0, cultivation - ?), debuff_json='{}' "
                "WHERE user_id=?",
                (row["target_realm"], row["target_stage"], row["cost"], user_id))
            if heart_reward:
                await conn.execute(
                    "UPDATE characters SET debuff_json=? WHERE user_id=?",
                    (debuff_json, user_id))
                daohang = await _grant_heart_daohang_conn(conn, user_id, now)
            label = realm_label(row["target_realm"], row["target_stage"])
            await game_events.emit_conn(
                conn, user_id, "breakthrough.big_success",
                {"target_realm": row["target_realm"], "target_stage": row["target_stage"],
                 "label": label}, now)
            mentor_milestone = await bonds_service.handle_disciple_breakthrough_conn(
                conn, user_id, row["target_realm"], row["target_stage"], now)
            if heart_reward:
                await game_events.emit_conn(
                    conn, user_id, HEART_SUCCESS_EVENT,
                    {"target_realm": row["target_realm"], "target_stage": row["target_stage"],
                     "label": label, "daohang": daohang,
                     "buff": HEART_TRIBULATION_BUFF_NAME}, now)
            return {"status": "big_success", "rate": row["rate"], "tribulation": True,
                    "label": label, "tribulation_log": logs,
                    "pill_used": BIG_BREAKTHROUGH[row["target_realm"]]["pill"],
                    "guarantee_bonus": row["guarantee_bonus"],
                    "heart_reward": heart_reward, "daohang": daohang,
                    "buff": HEART_TRIBULATION_BUFF_NAME if heart_reward else None,
                    "buff_seconds": HEART_TRIBULATION_BUFF_DURATION if heart_reward else 0,
                    "seclusion_pct": HEART_TRIBULATION_SECLUSION_PCT if heart_reward else 0.0,
                    "mentor_milestone": mentor_milestone}
        await conn.execute(
            "UPDATE tribulation_sessions SET hp=?, thunder_index=?, log_json=?, reward_flag=? WHERE user_id=?",
            (hp, idx + 1, json.dumps(logs, ensure_ascii=False), reward_flag, user_id))
        updated = await _session(conn, user_id)
        res = _tribulation_status(updated)
        res["last_log"] = logs[-2:]
        return res
