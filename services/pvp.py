"""切磋 / 天梯（spec §10）。"""
from __future__ import annotations

import random
import time

from services import character
from services import game_events, social
from services.combat import CombatRules, Combatant, simulate
from models import db

K_FACTOR = 32
DAILY_LIMIT = 10
WIN_REPUTATION = 3
LOSS_REPUTATION = 1
PVP_MAX_ROUNDS = 160
PVP_COMBAT_RULES = CombatRules(
    heal_factor=0.08,
    heal_decay_start_round=45,
    heal_decay_per_round=0.062,
    lifesteal_factor=0.40,
    shield_absorb_pct=0.40,
    damage_growth_start_round=45,
    damage_growth_per_round=0.018,
    damage_growth_cap=1.50,
    pressure_start_round=60,
    pressure_base_pct=0.002,
    pressure_growth_pct=0.00015,
    pressure_cap_pct=0.022,
    notice="斗法台禁制落下：疗伤、汲血与护盾皆受压，久战气机反噬。",
)

# 周结算奖池（#14）：取代即时发灵石，按本周有效声望排名发放。
WEEKLY_POOL_STONE = 6000
_WEEKLY_HEAD_SHARES = [0.30, 0.20, 0.14, 0.10, 0.08]  # 头部 5 名，余额均分其余有效参与者


def _day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _week(ts: int) -> str:
    return time.strftime("%Y-%W", time.localtime(ts))


def _weekly_share(idx: int, n: int) -> float:
    if n <= 0:
        return 0.0
    head_count = min(n, len(_WEEKLY_HEAD_SHARES))
    if n <= len(_WEEKLY_HEAD_SHARES):
        total = sum(_WEEKLY_HEAD_SHARES[:head_count])
        return _WEEKLY_HEAD_SHARES[idx] / total if total else 0.0
    if idx < len(_WEEKLY_HEAD_SHARES):
        return _WEEKLY_HEAD_SHARES[idx]
    rest = n - len(_WEEKLY_HEAD_SHARES)
    return (1.0 - sum(_WEEKLY_HEAD_SHARES)) / rest if rest > 0 else 0.0


def _expected(ra: int, rb: int) -> float:
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def _delta(ra: int, rb: int, score: float) -> int:
    return int(round(K_FACTOR * (score - _expected(ra, rb))))


async def ensure_rating(conn, user_id: int):
    await conn.execute(
        "INSERT OR IGNORE INTO pvp_ratings(user_id, rating, reputation, wins, losses, daily_count, daily_reset_at) "
        "VALUES(?,1000,0,0,0,0,0)",
        (user_id,))


async def _rating(conn, user_id: int):
    await ensure_rating(conn, user_id)
    cur = await conn.execute("SELECT * FROM pvp_ratings WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _rank_for_conn(conn, user_id: int, limit: int = 10):
    cur = await conn.execute(
        "SELECT user_id FROM pvp_ratings ORDER BY rating DESC, wins DESC LIMIT ?",
        (limit,))
    rows = await cur.fetchall()
    await cur.close()
    for idx, row in enumerate(rows, 1):
        if row["user_id"] == user_id:
            return idx
    return None


async def random_opponent(user_id: int):
    me = await character.get(user_id)
    if not me:
        return None
    my_rating = await db.fetchone(
        "SELECT rating FROM pvp_ratings WHERE user_id=?", (user_id,))
    rating = my_rating["rating"] if my_rating else 1000
    rows = await db.fetchall(
        "SELECT c.user_id, c.realm, COALESCE(p.rating, 1000) AS rating "
        "FROM characters c LEFT JOIN pvp_ratings p ON p.user_id=c.user_id "
        "WHERE c.user_id<>?",
        (user_id,))
    eligible = [
        row for row in rows
        if abs(row["realm"] - me.realm) <= 1
    ]
    close = [row for row in eligible if abs(row["rating"] - rating) <= 200]
    if close:
        eligible = close
    if not eligible:
        eligible = rows
    return random.choice(eligible)["user_id"] if eligible else None


async def opponent_from_arg(arg: str):
    arg = (arg or "").strip()
    if not arg:
        return {"status": "empty"}
    if arg.startswith("@"):
        username = arg[1:].strip().lower()
        if not username:
            return {"status": "not_found"}
        row = await db.fetchone(
            "SELECT tg_user_id, username FROM users WHERE lower(username)=?",
            (username,))
        if not row:
            return {"status": "not_found"}
        return {"status": "ok", "user_id": row["tg_user_id"],
                "name": "@" + (row["username"] or str(row["tg_user_id"]))}
    if arg.startswith("#") and arg[1:].isdigit():
        rank = int(arg[1:])
        if rank <= 0:
            return {"status": "not_found"}
        rows = await top(rank)
        if len(rows) < rank:
            return {"status": "not_found"}
        row = rows[rank - 1]
        return {"status": "ok", "user_id": row["user_id"],
                "name": row["username"] or f"榜第{rank}"}
    if arg.isdigit():
        row = await db.fetchone(
            "SELECT tg_user_id, username FROM users WHERE tg_user_id=?",
            (int(arg),))
        if row:
            return {"status": "ok", "user_id": row["tg_user_id"],
                    "name": row["username"] or row["tg_user_id"]}
    return {"status": "not_found"}


async def _validate_pair(attacker_id: int, defender_id: int = None) -> dict:
    if defender_id is None:
        defender_id = await random_opponent(attacker_id)
    if not defender_id:
        return {"status": "no_opponent"}
    if attacker_id == defender_id:
        return {"status": "self"}

    attacker = await character.get(attacker_id)
    defender = await character.get(defender_id)
    if not attacker or not defender:
        return {"status": "missing"}
    if abs(attacker.realm - defender.realm) > 1:
        return {"status": "realm_gap"}
    return {"status": "ok", "defender_id": defender_id}


async def preview_duel(attacker_id: int, defender_id: int = None) -> dict:
    res = await _validate_pair(attacker_id, defender_id)
    if res["status"] != "ok":
        return res
    row = await db.fetchone(
        "SELECT username FROM users WHERE tg_user_id=?",
        (res["defender_id"],))
    return {"status": "ok", "defender_id": res["defender_id"],
            "name": row["username"] if row and row["username"] else str(res["defender_id"])}


async def _display_name(user_id: int, fallback: str) -> str:
    row = await db.fetchone(
        "SELECT username FROM users WHERE tg_user_id=?", (user_id,))
    if row and row["username"]:
        return row["username"]
    return fallback


async def _combatant(user_id: int, name: str) -> Combatant:
    char = await character.get(user_id)
    st = await character.stats(char, pvp=True)
    skills = await character.get_skills(user_id)
    mods = await character.combat_mods(user_id)
    return Combatant(name=name, hp=st["hp"], mp=st["mp"], atk=st["atk"],
                     df=st["df"], spd=st["spd"], crit=st["crit"], skills=skills or ["普攻"],
                     **mods)


async def duel(attacker_id: int, defender_id: int = None, now: int = None,
               attacker_name: str = None, defender_name: str = None) -> dict:
    now = int(time.time()) if now is None else now
    pair = await _validate_pair(attacker_id, defender_id)
    if pair["status"] != "ok":
        return pair
    defender_id = pair["defender_id"]
    attacker_name = attacker_name or await _display_name(attacker_id, str(attacker_id))
    defender_name = defender_name or await _display_name(defender_id, str(defender_id))

    day = _day(now)
    async with db.transaction() as conn:
        ar = await _rating(conn, attacker_id)
        dr = await _rating(conn, defender_id)
        daily_count = ar["daily_count"] if ar["daily_reset_at"] == day else 0
        if daily_count >= DAILY_LIMIT:
            return {"status": "daily_limit", "limit": DAILY_LIMIT}
        await conn.execute(
            "UPDATE pvp_ratings SET daily_count=?, daily_reset_at=? WHERE user_id=?",
            (daily_count + 1, day, attacker_id))

    a = await _combatant(attacker_id, attacker_name)
    d = await _combatant(defender_id, defender_name)
    result = simulate(
        a, d, seed=random.getrandbits(32),
        max_rounds=PVP_MAX_ROUNDS, rules=PVP_COMBAT_RULES)
    attacker_win = result["winner"] is a

    week = _week(now)
    async with db.transaction() as conn:
        ar = await _rating(conn, attacker_id)
        dr = await _rating(conn, defender_id)
        old_a_rating, old_d_rating = ar["rating"], dr["rating"]
        old_a_rank = await _rank_for_conn(conn, attacker_id)
        old_d_rank = await _rank_for_conn(conn, defender_id)
        score = 1.0 if attacker_win else 0.0
        change = _delta(ar["rating"], dr["rating"], score)
        defender_change = _delta(dr["rating"], ar["rating"], 1.0 - score)
        new_a_rating = max(0, ar["rating"] + change)
        new_d_rating = max(0, dr["rating"] + defender_change)
        # 同一对手每日只计一次有效声望，降低互刷价值（积分仍照常变动，零和不通胀）。
        u1, u2 = sorted((attacker_id, defender_id))
        cur = await conn.execute(
            "SELECT 1 FROM pvp_daily_pairs WHERE u1=? AND u2=? AND day=?", (u1, u2, day))
        dup = await cur.fetchone()
        await cur.close()
        rep_counts = dup is None
        if rep_counts:
            await conn.execute(
                "INSERT OR IGNORE INTO pvp_daily_pairs(u1, u2, day) VALUES(?,?,?)", (u1, u2, day))
        attacker_rep = (WIN_REPUTATION if attacker_win else LOSS_REPUTATION) if rep_counts else 0
        defender_rep = (LOSS_REPUTATION if attacker_win else WIN_REPUTATION) if rep_counts else 0
        a_week = (ar["week_reputation"] if ar["week_tag"] == week else 0) + attacker_rep
        d_week = (dr["week_reputation"] if dr["week_tag"] == week else 0) + defender_rep
        await conn.execute(
            "UPDATE pvp_ratings SET rating=?, reputation=reputation+?, wins=wins+?, losses=losses+?, "
            "week_reputation=?, week_tag=? WHERE user_id=?",
            (new_a_rating, attacker_rep, 1 if attacker_win else 0,
             0 if attacker_win else 1, a_week, week, attacker_id))
        await conn.execute(
            "UPDATE pvp_ratings SET rating=?, reputation=reputation+?, wins=wins+?, losses=losses+?, "
            "week_reputation=?, week_tag=? WHERE user_id=?",
            (new_d_rating, defender_rep, 0 if attacker_win else 1,
             1 if attacker_win else 0, d_week, week, defender_id))
        # 不再即时发放灵石：移除无成本 faucet，改由 settle_weekly 按排名发奖池（#14）。
        winner_id = attacker_id if attacker_win else defender_id
        await game_events.emit_conn(
            conn, winner_id, "pvp.win",
            {"attacker_id": attacker_id, "defender_id": defender_id, "amount": 1}, now)
        new_a_rank = await _rank_for_conn(conn, attacker_id)
        new_d_rank = await _rank_for_conn(conn, defender_id)
        await social.queue_rank_change_conn(
            conn, attacker_id, old_a_rating, new_a_rating, old_a_rank, new_a_rank, now)
        await social.queue_rank_change_conn(
            conn, defender_id, old_d_rating, new_d_rating, old_d_rank, new_d_rank, now)

    return {"status": "ok", "win": attacker_win, "rating_delta": change,
            "reputation_gain": attacker_rep, "reputation_counted": rep_counts,
            "tier": tier(new_a_rating),
            "defender_id": defender_id, "log": result["log"],
            "rounds": result["rounds"], "finish_reason": result["reason"],
            "attacker_name": attacker_name, "defender_name": defender_name}


async def settle_weekly(now: int = None, pool: int = WEEKLY_POOL_STONE) -> list:
    """按本周有效声望排名发放奖池灵石，并清零本周声望（#14）。由调度周期调用。"""
    now = int(time.time()) if now is None else now
    week = _week(now)
    results = []
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT user_id, week_reputation FROM pvp_ratings "
            "WHERE week_tag=? AND week_reputation>0 ORDER BY week_reputation DESC, rating DESC",
            (week,))
        rows = await cur.fetchall()
        await cur.close()
        n = len(rows)
        if n == 0:
            return results
        payouts = [int(pool * _weekly_share(idx, n)) for idx in range(n)]
        for idx in range(pool - sum(payouts)):
            payouts[idx % n] += 1
        for idx, row in enumerate(rows):
            stone = payouts[idx]
            if stone > 0:
                await conn.execute(
                    "UPDATE characters SET spirit_stone = spirit_stone + ? WHERE user_id=?",
                    (stone, row["user_id"]))
            results.append({"user_id": row["user_id"], "rank": idx + 1,
                            "stone": stone, "reputation": row["week_reputation"]})
        await conn.execute(
            "UPDATE pvp_ratings SET week_reputation=0 WHERE week_tag=?", (week,))
    return results


async def top(limit: int = 10):
    rows = await db.fetchall(
        "SELECT p.user_id, p.rating, p.reputation, p.wins, p.losses, u.username "
        "FROM pvp_ratings p LEFT JOIN users u ON u.tg_user_id=p.user_id "
        "ORDER BY p.rating DESC, p.wins DESC LIMIT ?",
        (limit,))
    return [dict(row) for row in rows]


def tier(rating: int) -> str:
    if rating >= 1600:
        return "地仙"
    if rating >= 1400:
        return "仙品"
    if rating >= 1200:
        return "宝品"
    if rating >= 1000:
        return "灵品"
    return "凡品"
