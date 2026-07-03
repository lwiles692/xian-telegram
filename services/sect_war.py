"""宗门战据点：进攻守卫（复用战斗引擎）→ 累计积分 → 赛季结算发奖。"""
from __future__ import annotations

import random
import time

from config import sect_war as CFG
from models import db
from services import activity
from services import character
from services.combat import Combatant, simulate


def _season(now: int) -> str:
    return time.strftime("%Y-%m", time.localtime(now))


def total_drop_pct(base_drop: float, outpost: dict) -> float:
    """合算掉率加成 = 宗门福利 + 据点（矿脉）drop_pct，封顶 +20%。"""
    return min(0.20, float(base_drop) + float((outpost or {}).get("drop_pct", 0.0)))


def is_open(now: int) -> bool:
    """据点战是否在开放窗口内（周六 20:00–21:00，固定上海时区，跨机器确定）。"""
    lt = time.gmtime(int(now) + CFG.WAR_TZ_OFFSET_SECONDS)
    return (lt.tm_wday == CFG.WAR_WEEKDAY
            and CFG.WAR_START_HOUR <= lt.tm_hour < CFG.WAR_END_HOUR)


def _guard_combatant(outpost: dict) -> Combatant:
    g = outpost["guard"]
    return Combatant(name=g["name"], hp=g["hp"], mp=g["mp"], atk=g["atk"],
                     df=g["df"], spd=g["spd"], crit=g["crit"], skills=g["skills"])


async def capture(user_id: int, outpost_key: str, score: int = None, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    if outpost_key not in CFG.OUTPOSTS:
        return {"status": "bad_outpost"}
    if not is_open(now):
        return {"status": "closed",
                "weekday": CFG.WAR_WEEKDAY,
                "start_hour": CFG.WAR_START_HOUR, "end_hour": CFG.WAR_END_HOUR}
    outpost = CFG.OUTPOSTS[outpost_key]
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT sect_id FROM sect_members WHERE user_id=?", (user_id,))
        member = await cur.fetchone()
        await cur.close()
        if not member:
            return {"status": "not_member"}
        sect_id = member["sect_id"]
        row = await character._select_character(conn, user_id)
        if not row:
            return {"status": "missing"}
        welfare = await character._sect_welfare(conn, user_id)
        stamina, stamina_at = character._settled_stamina(row, now, welfare)
        if stamina < CFG.WAR_STAMINA_COST:
            await conn.execute(
                "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
                (stamina, stamina_at, user_id))
            await activity.record_virtual_window(
                user_id, "sect_war", outpost_key, now,
                CFG.WAR_NO_STAMINA_WINDOW_SECONDS, conn=conn)
            return {"status": "no_stamina", "need": CFG.WAR_STAMINA_COST, "have": stamina}
        left = stamina - CFG.WAR_STAMINA_COST
        await conn.execute(
            "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
            (left, stamina_at, user_id))
        await activity.record_virtual_window(
            user_id, "sect_war", outpost_key, now,
            CFG.WAR_ACTION_DURATION_SECONDS, conn=conn)
        char = character._from_row(row, left, stamina_at)
    # spec §8.1：先复用战斗引擎击败据点守卫，胜方才计入宗门积分；败则无积分。
    st = await character.stats(char)
    skills = await character.get_skills(user_id)
    mods = await character.combat_mods(user_id)
    player = Combatant(name="道友", hp=st["hp"], mp=st["mp"], atk=st["atk"],
                       df=st["df"], spd=st["spd"], crit=st["crit"],
                       skills=skills or ["普攻"], **mods)
    result = simulate(
        player, _guard_combatant(outpost),
        seed=random.getrandbits(32), max_rounds=None)
    if result["winner"] is not player:
        return {"status": "defeated", "outpost": outpost["name"],
                "guard": outpost["guard"]["name"], "stamina_left": char.stamina}
    gain = int(outpost["win_score"] if score is None else score)
    season = _season(now)
    async with db.transaction() as conn:
        # 复合主键 (sect_id, outpost_key)：一个宗门可同时持有多个据点，各自累计积分。
        await conn.execute(
            "INSERT INTO sect_outposts(sect_id, outpost_key, score, season, updated_at) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(sect_id, outpost_key) DO UPDATE SET score=score+?, season=?, updated_at=?",
            (sect_id, outpost_key, gain, season, now, gain, season, now))
        return {"status": "ok", "outpost": outpost["name"], "score": gain,
                "stamina_left": char.stamina}


async def settle_season(now: int = None) -> dict:
    """据点战赛季结算（spec §8.1"按宗门累计积分结算"）：积分最高的宗门夺魁，
    其成员获绑定道行奖励，并清空本季据点积分。幂等：同一 season 只结算一次。

    这是 sect_outposts.score 的消费方——积分不再是死数据。
    """
    now = int(time.time()) if now is None else now
    season = _season(now)
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM sect_war_rewards WHERE season=?", (season,))
        done = await cur.fetchone()
        await cur.close()
        if done:
            return {"status": "settled", "season": season}
        cur = await conn.execute(
            "SELECT sect_id, SUM(score) AS total FROM sect_outposts "
            "WHERE season=? GROUP BY sect_id HAVING total > 0 ORDER BY total DESC LIMIT 1",
            (season,))
        top = await cur.fetchone()
        await cur.close()
        if not top:
            return {"status": "no_participants", "season": season}
        winner_sect, winner_score = top["sect_id"], top["total"]
        cur = await conn.execute(
            "SELECT user_id FROM sect_members WHERE sect_id=?", (winner_sect,))
        members = await cur.fetchall()
        await cur.close()
        for m in members:
            await conn.execute(
                "UPDATE characters SET daohang=daohang+? WHERE user_id=?",
                (CFG.WAR_SEASON_DAOHANG_REWARD, m["user_id"]))
        await conn.execute(
            "INSERT INTO sect_war_rewards(season, sect_id, score, settled_at) VALUES(?,?,?,?)",
            (season, winner_sect, winner_score, now))
        # 结算后清空本季据点积分，下一季重新累计（buff 归属保留在 outpost 行）。
        await conn.execute("UPDATE sect_outposts SET score=0 WHERE season=?", (season,))
        return {"status": "ok", "season": season, "sect_id": winner_sect,
                "score": winner_score, "members": len(members),
                "daohang": CFG.WAR_SEASON_DAOHANG_REWARD}


async def bonuses_for_user(user_id: int) -> dict:
    """合并该宗门持有的**所有**据点 buff（多据点并存，各自加成累加）。"""
    rows = await db.fetchall(
        "SELECT o.outpost_key FROM sect_members m JOIN sect_outposts o ON o.sect_id=m.sect_id "
        "WHERE m.user_id=?",
        (user_id,))
    merged: dict = {}
    for row in rows:
        for key, val in CFG.OUTPOSTS.get(row["outpost_key"], {}).get("buff", {}).items():
            merged[key] = merged.get(key, 0.0) + float(val)
    return merged
