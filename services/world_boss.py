"""世界 Boss lite：群实例、累计伤害、贡献奖励（spec §5.3；分档与奖励重做 #14）。"""
from __future__ import annotations

import math
import random
import time

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import daohang as DAOHANG
from config.bosses import (DEFAULT_BOSS, WORLD_BOSSES, WORLD_BOSS_FULL_HP_CULTIVATORS,
                           boss_key_for_realm, canonical_boss_key)
from config import ascension as ASC_CFG, bonds as BONDS
from config.items import item_name
from handlers.common import action_callback_data
from services import ascension, character, game_events
from services.combat import Combatant, simulate
from models import db


def _day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _boss_combatant(key: str) -> Combatant:
    src = _boss_cfg(key)["combat"]
    return Combatant(name=src["name"], hp=src["hp"], mp=src["mp"], atk=src["atk"],
                     df=src["df"], spd=src["spd"], crit=src["crit"], skills=list(src["skills"]))


def _boss_cfg(key: str) -> dict:
    return WORLD_BOSSES[canonical_boss_key(key)]


def _tier_from_realms(realms: list[int]) -> str:
    if not realms:
        return DEFAULT_BOSS
    return boss_key_for_realm(sorted(realms)[len(realms) // 2])


def _scaled_total_hp(cfg: dict, cultivator_count: int) -> int:
    count = max(1, cultivator_count)
    scale = min(1.0, count / WORLD_BOSS_FULL_HP_CULTIVATORS)
    return max(1, int(round(cfg["total_hp"] * scale)))


def _special_reward_slots(participant_count: int) -> int:
    """多人小群至少给前 2 名特殊奖励；大群维持约前三分之一。"""
    if participant_count <= 1:
        return max(0, participant_count)
    return min(participant_count, max(2, participant_count // 3))


def _legacy_reward_slots(participant_count: int) -> int:
    return max(1, participant_count // 3)


def _drop_qty_for_rank(total: int, rank_index: int, slots: int, legacy_slots: int) -> int:
    if total <= 0 or rank_index >= slots:
        return 0
    if total < slots:
        return 1 if rank_index < total else 0
    if slots > legacy_slots:
        base = total // slots
        extra = total % slots
        return base + (1 if rank_index < extra else 0)
    return total // slots


def _split_drops_for_rank(drops: dict, rank_index: int, slots: int,
                          participant_count: int) -> dict:
    if rank_index >= slots:
        return {}
    legacy_slots = _legacy_reward_slots(participant_count)
    bundle = {}
    for key, total in drops.items():
        qty = _drop_qty_for_rank(int(total), rank_index, slots, legacy_slots)
        if qty > 0:
            bundle[key] = qty
    return bundle


def _ranked_bonus_shares(total: int, slots: int) -> list[int]:
    if slots <= 0 or total <= 0:
        return []
    weights = [slots - idx for idx in range(slots)]
    wsum = sum(weights)
    shares = [int(total * weight / wsum) for weight in weights]
    shares[0] += total - sum(shares)
    return shares


async def remember_cultivator(chat_id: int, user_id: int, now: int = None) -> bool:
    """记录本群已知修仙者；只有已创建角色的用户会计入 Boss 缩放。"""
    now = int(time.time()) if now is None else now
    if not await character.exists(user_id):
        return False
    await db.execute(
        "INSERT INTO bot_chat_members(chat_id, user_id, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen_at=?",
        (chat_id, user_id, now, now))
    return True


async def _known_group_realms(conn, chat_id: int) -> list[int]:
    cur = await conn.execute(
        "SELECT c.realm FROM bot_chat_members m "
        "JOIN characters c ON c.user_id = m.user_id "
        "WHERE m.chat_id = ?",
        (chat_id,))
    realms = [row["realm"] for row in await cur.fetchall()]
    await cur.close()
    return realms


async def _historical_damage_realms(conn, chat_id: int) -> list[int]:
    cur = await conn.execute(
        "SELECT c.realm FROM world_boss_damage d "
        "JOIN world_boss b ON b.id = d.boss_id "
        "JOIN characters c ON c.user_id = d.user_id "
        "WHERE b.chat_id = ? ORDER BY b.id DESC LIMIT 50",
        (chat_id,))
    realms = [row["realm"] for row in await cur.fetchall()]
    await cur.close()
    return realms


async def _select_tier(conn, chat_id: int) -> str:
    """按本群已知修仙者中位境界选档；无记录时兼容历史挑战者，最后默认筑基档。"""
    realms = await _known_group_realms(conn, chat_id)
    if not realms:
        realms = await _historical_damage_realms(conn, chat_id)
    return _tier_from_realms(realms)


async def _cultivator_count(conn, chat_id: int) -> int:
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM bot_chat_members m "
        "JOIN characters c ON c.user_id = m.user_id "
        "WHERE m.chat_id = ?",
        (chat_id,))
    row = await cur.fetchone()
    await cur.close()
    return int(row["n"] or 0)


async def remember_chat(chat_id: int, title: str = None, now: int = None):
    now = int(time.time()) if now is None else now
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=?, last_seen_at=?",
        (chat_id, title, now, title, now))


async def known_chats():
    rows = await db.fetchall("SELECT chat_id, title FROM bot_chats ORDER BY last_seen_at DESC")
    return [dict(row) for row in rows]


async def remember_message(boss_id: int, message_id: int):
    await db.execute(
        "UPDATE world_boss SET message_id=? WHERE id=?",
        (message_id, boss_id))


async def _active_row(conn, chat_id: int, now: int):
    cur = await conn.execute(
        "SELECT * FROM world_boss WHERE chat_id=? AND status='alive' ORDER BY id DESC LIMIT 1",
        (chat_id,))
    row = await cur.fetchone()
    await cur.close()
    if row and row["expire_at"] <= now:
        await conn.execute("UPDATE world_boss SET status='expired' WHERE id=?", (row["id"],))
        await _distribute(conn, row["id"], _boss_cfg(row["boss_key"]), now)
        return None
    return row


async def _latest_today(conn, chat_id: int, now: int):
    cur = await conn.execute(
        "SELECT * FROM world_boss WHERE chat_id=? ORDER BY id DESC LIMIT 1",
        (chat_id,))
    row = await cur.fetchone()
    await cur.close()
    if row and _day(row["spawn_at"]) == _day(now):
        return row
    return None


async def ensure_active(chat_id: int, now: int = None):
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        row = await _active_row(conn, chat_id, now)
        if row:
            return row
        latest = await _latest_today(conn, chat_id, now)
        if latest:
            return latest
        boss_key = await _select_tier(conn, chat_id)
        cfg = WORLD_BOSSES[boss_key]
        cultivator_count = await _cultivator_count(conn, chat_id)
        total_hp = _scaled_total_hp(cfg, cultivator_count)
        await conn.execute(
            "INSERT INTO world_boss(chat_id, boss_key, total_hp, remaining_hp, spawn_at, expire_at, "
            "status, cultivator_count) VALUES(?,?,?,?,?,?, 'alive', ?)",
            (chat_id, boss_key, total_hp, total_hp, now, now + cfg["duration"], max(1, cultivator_count)))
        cur = await conn.execute(
            "SELECT * FROM world_boss WHERE chat_id=? AND status='alive' ORDER BY id DESC LIMIT 1",
            (chat_id,))
        created = await cur.fetchone()
        await cur.close()
        return created


def broadcast_text(boss_row) -> str:
    cfg = _boss_cfg(boss_row["boss_key"])
    return (
        f"🐲 世界 Boss「{cfg['name']}」现世！\n"
        f"气血 {boss_row['remaining_hp']}/{boss_row['total_hp']}，持续 2 小时。\n"
        "发送 /boss 或点击挑战合力诛妖。"
    )


async def broadcast_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚔️ 挑战 Boss",
            callback_data=await action_callback_data(None, "boss:hit")),
         InlineKeyboardButton(text="🐲 查看战况", callback_data="boss:status")]
    ])


async def scheduled_spawn(bot, now: int = None):
    spawned = []
    for chat in await known_chats():
        boss = await ensure_active(chat["chat_id"], now)
        if boss["status"] != "alive":
            continue
        text = broadcast_text(boss)
        markup = await broadcast_markup()
        try:
            if boss["message_id"]:
                await bot.edit_message_text(
                    text=text, chat_id=chat["chat_id"], message_id=boss["message_id"],
                    reply_markup=markup)
            else:
                msg = await bot.send_message(chat["chat_id"], text, reply_markup=markup)
                await remember_message(boss["id"], msg.message_id)
        except Exception:
            try:
                msg = await bot.send_message(chat["chat_id"], text, reply_markup=markup)
                await remember_message(boss["id"], msg.message_id)
            except Exception:
                pass
        spawned.append(dict(boss))
    return spawned


async def status(chat_id: int, now: int = None):
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        boss = await _active_row(conn, chat_id, now)
        if not boss:
            boss = await _latest_today(conn, chat_id, now)
        if not boss:
            return {"status": "none"}
        rows = await _leaderboard(conn, boss["id"])
    return {"status": boss["status"], "boss": dict(boss), "leaderboard": rows}


async def _leaderboard(conn, boss_id: int, limit: int = 5):
    cur = await conn.execute(
        "SELECT d.user_id, d.damage, u.username FROM world_boss_damage d "
        "LEFT JOIN users u ON u.tg_user_id=d.user_id "
        "WHERE d.boss_id=? ORDER BY d.damage DESC LIMIT ?",
        (boss_id, limit))
    rows = await cur.fetchall()
    await cur.close()
    return [dict(row) for row in rows]


async def challenge(chat_id: int, user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    await remember_cultivator(chat_id, user_id, now)
    boss = await ensure_active(chat_id, now)
    cfg = _boss_cfg(boss["boss_key"])
    if boss["status"] == "expired":
        return {"status": "expired"}
    if boss["status"] == "defeated":
        return {"status": "defeated"}
    if boss["remaining_hp"] <= 0:
        return {"status": "defeated"}

    reserve = await character.reserve_stamina_for_action(user_id, cfg["stamina"])
    if reserve["status"] != "ok":
        return reserve
    char = reserve["char"]
    st = await character.stats(char)
    skills = await character.get_skills(user_id)
    mods = await character.combat_mods(user_id)
    player = Combatant(name="道友", hp=st["hp"], mp=st["mp"], atk=st["atk"],
                       df=st["df"], spd=st["spd"], crit=st["crit"], skills=skills or ["普攻"],
                       **mods)
    target = _boss_combatant(boss["boss_key"])
    result = simulate(player, target, seed=random.getrandbits(32))
    damage = max(1, target.max_hp - result["d_hp"])

    rewards = []
    defeated = False
    challenge_daohang = 0
    async with db.transaction() as conn:
        current = await _active_row(conn, chat_id, now)
        if not current:
            # Boss 已被他人击杀/过期，退还本次预扣的精力。
            await conn.execute(
                "UPDATE characters SET stamina = stamina + ? WHERE user_id=?",
                (cfg["stamina"], user_id))
            return {"status": "expired"}
        damage = min(damage, current["remaining_hp"])
        remaining = max(0, current["remaining_hp"] - damage)
        await conn.execute(
            "UPDATE world_boss SET remaining_hp=?, status=? WHERE id=?",
            (remaining, "defeated" if remaining <= 0 else "alive", current["id"]))
        await conn.execute(
            "INSERT INTO world_boss_damage(boss_id, user_id, damage) VALUES(?,?,?) "
            "ON CONFLICT(boss_id, user_id) DO UPDATE SET damage = damage + ?",
            (current["id"], user_id, damage, damage))
        challenge_daohang = await character.grant_regular_daohang_conn(
            conn, user_id, DAOHANG.WORLD_BOSS_CHALLENGE_DAOHANG,
            "world_boss_challenge", now, realm=char.realm)
        leaderboard = await _leaderboard(conn, current["id"])
        if remaining <= 0:
            defeated = True
            rewards = await _distribute(conn, current["id"], cfg, now)
        partner_combo = await _partner_combo_flavor_conn(conn, current["id"], user_id)
        await game_events.emit_conn(
            conn, user_id, "world_boss.challenge",
            {"boss_key": current["boss_key"], "boss_name": cfg["name"],
             "damage": damage, "defeated": defeated, "amount": 1},
            now)

    return {"status": "ok", "damage": damage, "remaining_hp": remaining,
            "total_hp": boss["total_hp"], "boss_name": cfg["name"], "defeated": defeated,
            "leaderboard": leaderboard, "rewards": rewards, "boss_id": boss["id"],
            "stamina_left": reserve["stamina_left"], "daohang": challenge_daohang,
            "partner_combo": partner_combo}


async def _partner_combo_flavor_conn(conn, boss_id: int, user_id: int) -> str | None:
    cur = await conn.execute(
        "SELECT b.b_id, u.username FROM social_bonds b "
        "LEFT JOIN users u ON u.tg_user_id=b.b_id "
        "WHERE b.kind=? AND b.status=? AND b.a_id=? LIMIT 1",
        (BONDS.KIND_PARTNER, BONDS.STATUS_ACTIVE, user_id))
    bond = await cur.fetchone()
    await cur.close()
    if not bond:
        return None
    cur = await conn.execute(
        "SELECT damage FROM world_boss_damage WHERE boss_id=? AND user_id=?",
        (boss_id, bond["b_id"]))
    damage = await cur.fetchone()
    await cur.close()
    if not damage or int(damage["damage"] or 0) <= 0:
        return None
    partner_name = bond["username"] or str(bond["b_id"])
    return f"💞 与道侣{partner_name}并肩合击，灵犀相照。"


async def _distribute(conn, boss_id: int, cfg: dict, now: int = None):
    """参与奖 + 软化分层贡献奖；小群特殊掉落至少覆盖前 2 名。"""
    now = int(time.time()) if now is None else now
    cur = await conn.execute(
        "SELECT user_id, damage FROM world_boss_damage WHERE boss_id=? ORDER BY damage DESC",
        (boss_id,))
    rows = await cur.fetchall()
    await cur.close()
    n = len(rows)
    if n == 0:
        return []
    pool = cfg["stone_pool"]
    # 参与奖：均分 25% 池，到场即有收益。
    participation = max(10, int(pool * 0.25 / n))
    remaining = max(0, pool - participation * n)
    # 贡献奖：按伤害平方根加权，压缩头尾差距，抑制强者滚雪球。
    weights = [math.sqrt(max(1, row["damage"])) for row in rows]
    wsum = sum(weights) or 1.0
    # 稀有掉落分摊给前列；多人小群至少覆盖前 2 名，避免奖励独归榜首。
    special_slots = _special_reward_slots(n)
    bonus_shares = _ranked_bonus_shares(int(pool * 0.05), special_slots)
    rewards = []
    for idx, row in enumerate(rows):
        stone = participation + int(remaining * weights[idx] / wsum)
        if idx < len(bonus_shares):
            stone += bonus_shares[idx]
        await conn.execute(
            "UPDATE characters SET spirit_stone = spirit_stone + ? WHERE user_id=?",
            (stone, row["user_id"]))
        drops = _split_drops_for_rank(cfg["drops"], idx, special_slots, n)
        for key, qty in drops.items():
            await conn.execute(
                "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
                "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = qty + ?",
                (row["user_id"], key, qty, qty))
        # T3.2 源之三：化神世界 Boss 前列额外发飞升点（账号级，非灵石经济）。
        asc_points = 0
        if cfg.get("realm") == ASC_CFG.BOSS_ASCENSION_REALM and idx < len(ASC_CFG.BOSS_RANK_POINTS):
            asc_points = ASC_CFG.BOSS_RANK_POINTS[idx]
            await ascension.add_points_conn(
                conn, row["user_id"], asc_points, now,
                source="world_boss", meta={"rank": idx + 1, "boss_id": boss_id})
        daohang = 0
        if idx < len(DAOHANG.WORLD_BOSS_RANK_DAOHANG):
            daohang = await character.grant_regular_daohang_conn(
                conn, row["user_id"], DAOHANG.WORLD_BOSS_RANK_DAOHANG[idx],
                "world_boss_rank", now)
        rewards.append({"user_id": row["user_id"], "stone": stone, "drops": drops,
                        "rank": idx + 1, "ascension_points": asc_points,
                        "daohang": daohang})
    return rewards


def reward_text(rewards: list) -> str:
    if not rewards:
        return ""
    base = f"击杀奖励已结算，{len(rewards)} 位道友按贡献分润灵石"
    daohang_total = sum(row.get("daohang", 0) for row in rewards)
    daohang_text = f"，道行共+{daohang_total}" if daohang_total else ""
    drop_rows = [row for row in rewards if row["drops"]]
    if not drop_rows:
        return base + daohang_text + "。"
    totals = {}
    for row in drop_rows:
        for key, qty in row["drops"].items():
            totals[key] = totals.get(key, 0) + qty
    drops = "、".join(f"{item_name(key)}×{qty}" for key, qty in totals.items())
    prefix = "前列" if len(drop_rows) > 1 else "榜首"
    return f"{base}，{prefix}另分 {drops}{daohang_text}。"
