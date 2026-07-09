from __future__ import annotations

"""低频群播报与天梯 DM 通知队列。"""

import json
import logging
import time

from config import realms as R
from config.items import item_name
from config.social import DAILY_LIMITS, MAX_ATTEMPTS
from models import db
from services import pvp

log = logging.getLogger("xian.social")


def _day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


async def queue_from_event_conn(conn, user_id: int, event_type: str,
                                payload: dict | None = None, now: int = None):
    now = int(time.time()) if now is None else now
    payload = payload or {}
    if "name" not in payload and "username" not in payload:
        payload = {**payload, "name": await _name(conn, user_id)}
    text = _group_text(event_type, payload)
    if text:
        chat_id = await _recent_chat(conn, user_id)
        if chat_id is not None and await _consume_limit(conn, user_id, event_type, now):
            await _insert(conn, chat_id, user_id, event_type, text, now)
    dm_text = _dm_text(event_type, payload)
    if dm_text:
        await _insert(conn, None, user_id, event_type, dm_text, now)


async def queue_rank_change_conn(conn, user_id: int, old_rating: int, new_rating: int,
                                 old_rank: int | None, new_rank: int | None,
                                 now: int = None):
    now = int(time.time()) if now is None else now
    old_tier = pvp.tier(max(0, old_rating))
    new_tier = pvp.tier(max(0, new_rating))
    if new_tier != old_tier:
        direction = "晋入" if _tier_order(new_tier) > _tier_order(old_tier) else "跌至"
        text = f"⚔️ 天梯变动：你已由{old_tier}{direction}{new_tier}，当前积分 {new_rating}。"
        await _insert(conn, None, user_id, "pvp.tier_change", text, now)
        if _tier_order(new_tier) > _tier_order(old_tier):
            chat_id = await _recent_chat(conn, user_id)
            if chat_id is not None and await _consume_limit(conn, user_id, "pvp.tier_up", now):
                name = await _name(conn, user_id)
                await _insert(
                    conn, chat_id, user_id, "pvp.tier_up",
                    f"⚔️ {name} 天梯晋入「{new_tier}」，剑名又重一分。", now)
    if old_rank != new_rank and (old_rank or 99) > 10 >= (new_rank or 99):
        await _insert(conn, None, user_id, "pvp.top_enter",
                      f"🏆 你已杀入天梯 Top {new_rank}。", now)
    if old_rank is not None and old_rank <= 10 and (new_rank is None or new_rank > 10):
        await _insert(conn, None, user_id, "pvp.top_leave",
                      "🏆 你已跌出天梯 Top 10，榜上风云又变。", now)
    await conn.execute(
        "INSERT INTO pvp_rank_snapshots(user_id, tier, top_rank, rating, updated_at) "
        "VALUES(?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET tier=?, top_rank=?, rating=?, updated_at=?",
        (user_id, new_tier, new_rank, new_rating, now,
         new_tier, new_rank, new_rating, now))


async def _recent_chat(conn, user_id: int):
    cur = await conn.execute(
        "SELECT chat_id FROM bot_chat_members WHERE user_id=? ORDER BY last_seen_at DESC LIMIT 1",
        (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row["chat_id"] if row else None


async def _name(conn, user_id: int) -> str:
    cur = await conn.execute("SELECT username FROM users WHERE tg_user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row["username"] if row and row["username"] else str(user_id)


async def _consume_limit(conn, user_id: int, event_type: str, now: int) -> bool:
    limit = DAILY_LIMITS.get(event_type)
    if not limit:
        return False
    period = _day(now)
    cur = await conn.execute(
        "SELECT count FROM social_broadcast_limits "
        "WHERE user_id=? AND event_type=? AND period=?",
        (user_id, event_type, period))
    row = await cur.fetchone()
    await cur.close()
    count = int(row["count"] if row else 0)
    if count >= limit:
        return False
    await conn.execute(
        "INSERT INTO social_broadcast_limits(user_id, event_type, period, count) "
        "VALUES(?,?,?,1) "
        "ON CONFLICT(user_id, event_type, period) DO UPDATE SET count=count+1",
        (user_id, event_type, period))
    return True


async def _insert(conn, chat_id, user_id: int, event_type: str, text: str, now: int):
    await conn.execute(
        "INSERT INTO social_broadcasts(chat_id, user_id, event_type, text, created_at, next_attempt_at) "
        "VALUES(?,?,?,?,?,?)",
        (chat_id, user_id, event_type, text, now, now))


def _tier_order(name: str) -> int:
    return {"凡品": 0, "灵品": 1, "宝品": 2, "仙品": 3, "地仙": 4}.get(name, 0)


def _group_text(event_type: str, payload: dict) -> str:
    name = payload.get("username") or payload.get("name") or "有位道友"
    if event_type == "breakthrough.big_success":
        label = payload.get("label") or R.realm_label(payload.get("target_realm", 0), payload.get("target_stage", 0))
        return f"✨ {name} 破境成功，晋入「{label}」。"
    if event_type == "breakthrough.heart_success":
        label = payload.get("label") or R.realm_label(payload.get("target_realm", 0), payload.get("target_stage", 0))
        return f"🌀 {name} 直面心魔而不退，道心通明，晋入「{label}」。"
    if event_type == "breakthrough.heart_fail":
        return f"🌀 {name} 直面心魔失守，道基震荡，来日仍可再证本心。"
    if event_type == "explore.boss_win":
        return f"🐲 {name} 斩杀妖王「{payload.get('mob', '妖王')}」，满身风尘而归。"
    if event_type == "explore.rare_drop":
        drops = payload.get("drops") or {}
        shown = "、".join(f"{item_name(k)}×{v}" for k, v in drops.items())
        return f"🎁 {name} 历练得稀珍：{shown}。"
    if event_type == "sect.upgrade":
        return f"⛩️ 宗门「{payload.get('sect', '某宗')}」升至 {payload.get('level')} 级。"
    if event_type == "ascension.trial":
        return f"🌌 {name} 飞升试炼功成，获飞升点 ×{payload.get('points', 1)}。"
    if event_type == "ascension.upgrade":
        passive = payload.get("passive_name", "飞升被动")
        title = payload.get("title") or ""
        tail = f"，尊号「{title}」传开" if title else ""
        return f"🌌 {name} 飞升精进，「{passive}」圆满{tail}。"
    return ""


def _dm_text(event_type: str, payload: dict) -> str:
    if event_type == "pvp.rating_notice":
        return str(payload.get("text") or "")
    return ""


async def flush_broadcasts(bot, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    rows = await db.fetchall(
        "SELECT * FROM social_broadcasts "
        "WHERE status='pending' AND next_attempt_at<=? ORDER BY id LIMIT 20",
        (now,))
    sent = failed = 0
    for row in rows:
        target = row["chat_id"] if row["chat_id"] is not None else row["user_id"]
        try:
            await bot.send_message(target, row["text"])
            await db.execute(
                "UPDATE social_broadcasts SET status='sent', sent_at=? WHERE id=?",
                (now, row["id"]))
            sent += 1
        except Exception as exc:  # pragma: no cover - Telegram transport
            log.warning("social send failed id=%s: %s", row["id"], exc)
            attempts = int(row["attempts"] or 0) + 1
            if attempts >= MAX_ATTEMPTS:
                await db.execute(
                    "UPDATE social_broadcasts SET status='failed', attempts=?, next_attempt_at=? WHERE id=?",
                    (attempts, now, row["id"]))
            else:
                await db.execute(
                    "UPDATE social_broadcasts SET attempts=?, next_attempt_at=? WHERE id=?",
                    (attempts, now + 60 * attempts, row["id"]))
            failed += 1
    return {"sent": sent, "failed": failed}


def payload_json(payload: dict) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)
