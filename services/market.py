"""玩家一口价坊市（v2 M5）。"""
from __future__ import annotations

import logging
import time

from config.items import is_tradable, item_name
from models import db
from services import character

log = logging.getLogger("xian.market")

MARKET_TAX_RATE = 0.05
MIN_PRICE = 1
MARKET_BROADCAST_WINDOW = 3600
MARKET_BROADCAST_LIMIT = 10
AUDIT_FREQUENT_WINDOW_SECONDS = 24 * 3600
AUDIT_FREQUENT_MIN_TRADES = 3


async def list_active(limit: int = 20) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM market_listings WHERE status='active' ORDER BY created_at LIMIT ?",
        (limit,))
    return [_format(row) for row in rows]


async def create_listing(seller_id: int, item_key: str, qty: int, price: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    qty = int(qty)
    price = int(price)
    if qty <= 0 or price < MIN_PRICE:
        return {"status": "bad_request"}
    if not is_tradable(item_key):
        return {"status": "no_trade", "item": item_name(item_key)}
    async with db.transaction() as conn:
        have = await character.item_qty_conn(conn, seller_id, item_key, bound=0)
        if have < qty:
            return {"status": "no_item", "have": have}
        await character.consume_item_conn(conn, seller_id, item_key, qty, bound=0)
        cur = await conn.execute(
            "INSERT INTO market_listings(seller_id, item_key, qty, price, status, created_at, updated_at) "
            "VALUES(?,?,?,?, 'active', ?, ?)",
            (seller_id, item_key, qty, price, now, now))
        listing_id = cur.lastrowid
        await cur.close()
        return {"status": "ok", "listing_id": listing_id, "item": item_name(item_key),
                "qty": qty, "price": price}


async def buy(buyer_id: int, listing_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM market_listings WHERE id=?", (listing_id,))
        listing = await cur.fetchone()
        await cur.close()
        if not listing or listing["status"] != "active":
            return {"status": "not_available"}
        if listing["seller_id"] == buyer_id:
            return {"status": "self_buy"}
        cur = await conn.execute("SELECT spirit_stone FROM characters WHERE user_id=?", (buyer_id,))
        buyer = await cur.fetchone()
        await cur.close()
        if not buyer:
            return {"status": "missing"}
        if buyer["spirit_stone"] < listing["price"]:
            return {"status": "no_stone", "need": listing["price"], "have": buyer["spirit_stone"]}
        tax = int(listing["price"] * MARKET_TAX_RATE)
        seller_gain = listing["price"] - tax
        await conn.execute(
            "UPDATE characters SET spirit_stone=spirit_stone-? WHERE user_id=?",
            (listing["price"], buyer_id))
        await conn.execute(
            "UPDATE characters SET spirit_stone=spirit_stone+? WHERE user_id=?",
            (seller_gain, listing["seller_id"]))
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty=qty+?",
            (buyer_id, listing["item_key"], listing["qty"], listing["qty"]))
        await conn.execute(
            "UPDATE market_listings SET status='sold', buyer_id=?, updated_at=? "
            "WHERE id=? AND status='active'",
            (buyer_id, now, listing_id))
        return {"status": "ok", "item": item_name(listing["item_key"]), "qty": listing["qty"],
                "price": listing["price"], "tax": tax, "seller_gain": seller_gain}


async def cancel(seller_id: int, listing_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM market_listings WHERE id=?", (listing_id,))
        listing = await cur.fetchone()
        await cur.close()
        if not listing or listing["status"] != "active":
            return {"status": "not_available"}
        if listing["seller_id"] != seller_id:
            return {"status": "forbidden"}
        cur = await conn.execute(
            "UPDATE market_listings SET status='cancelled', updated_at=? "
            "WHERE id=? AND status='active'",
            (now, listing_id))
        changed = cur.rowcount
        await cur.close()
        if not changed:
            return {"status": "not_available"}
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty=qty+?",
            (seller_id, listing["item_key"], listing["qty"], listing["qty"]))
        return {"status": "ok", "item": item_name(listing["item_key"]), "qty": listing["qty"]}


async def audit_suspicious(limit_price: int = 1_000_000) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM market_listings WHERE price>=? ORDER BY price DESC",
        (limit_price,))
    return [_format(row) for row in rows]


async def audit_frequent_trades(now: int = None, window_seconds: int = AUDIT_FREQUENT_WINDOW_SECONDS,
                                min_trades: int = AUDIT_FREQUENT_MIN_TRADES) -> list[dict]:
    now = int(time.time()) if now is None else now
    since = now - int(window_seconds)
    rows = await db.fetchall(
        "SELECT seller_id, buyer_id, COUNT(*) AS trades, SUM(price) AS total_price, "
        "MIN(updated_at) AS first_at, MAX(updated_at) AS last_at "
        "FROM market_listings "
        "WHERE status='sold' AND buyer_id IS NOT NULL AND updated_at>? AND updated_at<=? "
        "GROUP BY seller_id, buyer_id HAVING trades>=? "
        "ORDER BY trades DESC, total_price DESC",
        (since, now, int(min_trades)))
    return [dict(row) for row in rows]


async def audit_report(limit_price: int = 1_000_000, now: int = None,
                       window_seconds: int = AUDIT_FREQUENT_WINDOW_SECONDS,
                       min_trades: int = AUDIT_FREQUENT_MIN_TRADES) -> dict:
    return {
        "high_price": await audit_suspicious(limit_price),
        "frequent_trades": await audit_frequent_trades(
            now=now, window_seconds=window_seconds, min_trades=min_trades),
    }


async def notify_recent_listings(bot, now: int = None) -> dict:
    """每小时向已知群汇总新上架的在售挂单；无新单则静默。"""
    now = int(time.time()) if now is None else now
    chats = await db.fetchall("SELECT chat_id FROM bot_chats ORDER BY last_seen_at DESC")
    sent = failed = skipped = listings = 0
    for chat in chats:
        res = await _notify_recent_listings_for_chat(bot, chat["chat_id"], now)
        if res["status"] == "sent":
            sent += 1
            listings += res["listings"]
        elif res["status"] == "failed":
            failed += 1
        else:
            skipped += 1
    return {"sent": sent, "failed": failed, "skipped": skipped, "listings": listings}


async def _notify_recent_listings_for_chat(bot, chat_id: int, now: int) -> dict:
    since = await _last_market_broadcast_at(chat_id, now)
    rows = await _new_active_listings(since, now, MARKET_BROADCAST_LIMIT)
    total = await _new_active_listing_count(since, now)
    if total <= 0:
        await _remember_market_broadcast(chat_id, now)
        return {"status": "skipped", "listings": 0}

    text = _recent_listings_text(rows, total)
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:
        log.warning(
            "market broadcast send failed chat_id=%s listings=%s: %s",
            chat_id, total, exc)
        await _remember_market_broadcast(chat_id, now)
        return {"status": "failed", "listings": total}
    await _remember_market_broadcast(chat_id, now)
    return {"status": "sent", "listings": total}


async def _last_market_broadcast_at(chat_id: int, now: int) -> int:
    row = await db.fetchone(
        "SELECT last_notified_at FROM market_broadcast_state WHERE chat_id=?",
        (chat_id,))
    if row:
        return int(row["last_notified_at"])
    return now - MARKET_BROADCAST_WINDOW - 1


async def _remember_market_broadcast(chat_id: int, now: int):
    await db.execute(
        "INSERT INTO market_broadcast_state(chat_id, last_notified_at) VALUES(?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET last_notified_at=?",
        (chat_id, now, now))


async def _new_active_listings(since: int, now: int, limit: int) -> list[dict]:
    rows = await db.fetchall(
        "SELECT l.*, u.username FROM market_listings l "
        "LEFT JOIN users u ON u.tg_user_id=l.seller_id "
        "WHERE l.status='active' AND l.created_at>? AND l.created_at<=? "
        "ORDER BY l.created_at, l.id LIMIT ?",
        (since, now, limit))
    return [dict(row) for row in rows]


async def _new_active_listing_count(since: int, now: int) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM market_listings "
        "WHERE status='active' AND created_at>? AND created_at<=?",
        (since, now))
    return int(row["n"] or 0)


def _recent_listings_text(rows: list[dict], total: int) -> str:
    lines = [
        "🏷️ 坊市上新",
        f"本轮有 {total} 单新上架：",
    ]
    for idx, row in enumerate(rows, start=1):
        seller = row.get("username") or f"道友{row['seller_id']}"
        lines.append(
            f"{idx}. #{row['id']} {item_name(row['item_key'])}×{row['qty']} "
            f"· {row['price']}灵石 · {seller}")
    if total > len(rows):
        lines.append(f"另有 {total - len(rows)} 单可在 /market 查看。")
    lines.append("发送 /market 查看和购买。")
    return "\n".join(lines)


def _format(row) -> dict:
    return {
        "id": row["id"],
        "seller_id": row["seller_id"],
        "buyer_id": row["buyer_id"],
        "item_key": row["item_key"],
        "item": item_name(row["item_key"]),
        "qty": row["qty"],
        "price": row["price"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
