from __future__ import annotations

"""英式拍卖行服务：挂拍、托管与撤拍（spec-v3 §6 / M2）。"""

import logging
import time

from config import auction as CFG
from config.items import ITEMS, equipment_slot, is_tradable, item_name
from models import db
from services import character, game_events, social

log = logging.getLogger("xian.auction")


def _now(now: int = None) -> int:
    return int(time.time()) if now is None else int(now)


def _validate_start_price(start_price: int, floor: int) -> dict | None:
    if int(start_price) < int(floor):
        return {"status": "price_too_low", "floor": int(floor)}
    return None


def _validate_buyout(start_price: int, buyout: int | None) -> dict | None:
    if buyout is None:
        return None
    min_buyout = CFG.min_buyout_price(start_price)
    if int(buyout) < min_buyout:
        return {"status": "bad_buyout", "min_buyout": min_buyout}
    return None


async def _active_count(conn, seller_id: int) -> int:
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM auctions WHERE seller_id=? AND status=?",
        (seller_id, CFG.STATUS_ACTIVE))
    row = await cur.fetchone()
    await cur.close()
    return int(row["n"] or 0)


async def _listing_fee_quote(conn, seller_id: int, start_price: int) -> dict:
    fee = CFG.listing_fee(start_price)
    cur = await conn.execute(
        "SELECT spirit_stone FROM characters WHERE user_id=?",
        (seller_id,))
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return {"status": "missing"}
    if int(row["spirit_stone"]) < fee:
        return {"status": "no_stone", "need": fee, "have": int(row["spirit_stone"])}
    return {"status": "ok", "fee": fee}


async def _charge_listing_fee(conn, seller_id: int, fee: int) -> None:
    await conn.execute(
        "UPDATE characters SET spirit_stone=spirit_stone-? WHERE user_id=?",
        (fee, seller_id))


async def _stone_balance(conn, user_id: int) -> dict:
    cur = await conn.execute(
        "SELECT spirit_stone FROM characters WHERE user_id=?",
        (user_id,))
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return {"status": "missing"}
    return {"status": "ok", "stone": int(row["spirit_stone"])}


async def _charge_stone(conn, user_id: int, amount: int) -> dict:
    amount = int(amount)
    if amount <= 0:
        return {"status": "ok", "paid": 0}
    balance = await _stone_balance(conn, user_id)
    if balance["status"] != "ok":
        return balance
    if balance["stone"] < amount:
        return {"status": "no_stone", "need": amount, "have": balance["stone"]}
    await conn.execute(
        "UPDATE characters SET spirit_stone=spirit_stone-? WHERE user_id=?",
        (amount, user_id))
    return {"status": "ok", "paid": amount}


async def _refund_stone(conn, user_id: int, amount: int) -> None:
    if int(amount) <= 0:
        return
    await conn.execute(
        "UPDATE characters SET spirit_stone=spirit_stone+? WHERE user_id=?",
        (int(amount), user_id))


async def _record_bid(conn, auction_id: int, bidder_id: int, amount: int, now: int) -> None:
    await conn.execute(
        "INSERT INTO auction_bids(auction_id, bidder_id, amount, bid_at) VALUES(?,?,?,?)",
        (auction_id, bidder_id, int(amount), int(now)))


async def _set_escrow(conn, auction_id: int, bidder_id: int, amount: int) -> None:
    await conn.execute(
        "INSERT INTO auction_escrow(auction_id, bidder_id, amount) VALUES(?,?,?) "
        "ON CONFLICT(auction_id, bidder_id) DO UPDATE SET amount=?",
        (auction_id, bidder_id, int(amount), int(amount)))


async def _clear_escrow(conn, auction_id: int, bidder_id: int | None = None) -> None:
    if bidder_id is None:
        await conn.execute("DELETE FROM auction_escrow WHERE auction_id=?", (auction_id,))
    else:
        await conn.execute(
            "DELETE FROM auction_escrow WHERE auction_id=? AND bidder_id=?",
            (auction_id, bidder_id))


async def _escrow_amount(conn, auction_id: int, bidder_id: int) -> int:
    cur = await conn.execute(
        "SELECT amount FROM auction_escrow WHERE auction_id=? AND bidder_id=?",
        (auction_id, bidder_id))
    row = await cur.fetchone()
    await cur.close()
    return int(row["amount"]) if row else 0


async def _refund_all_escrow(conn, auction_id: int) -> int:
    cur = await conn.execute("SELECT bidder_id, amount FROM auction_escrow WHERE auction_id=?", (auction_id,))
    rows = await cur.fetchall()
    await cur.close()
    total = 0
    for row in rows:
        amount = int(row["amount"])
        await _refund_stone(conn, row["bidder_id"], amount)
        total += amount
    await _clear_escrow(conn, auction_id)
    return total


async def _add_item(conn, user_id: int, item_key: str, qty: int) -> None:
    await conn.execute(
        "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
        "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty=qty+?",
        (user_id, item_key, int(qty), int(qty)))


async def _return_lot(conn, auction) -> None:
    if auction["kind"] == CFG.KIND_EQUIPMENT:
        await conn.execute(
            "UPDATE item_instances SET status=? WHERE id=? AND user_id=?",
            (CFG.INSTANCE_STATUS_NORMAL, auction["instance_id"], auction["seller_id"]))
    else:
        await _add_item(conn, auction["seller_id"], auction["item_key"], auction["qty"])


async def _insert_auction(conn, seller_id: int, kind: str, start_price: int, buyout: int | None,
                          end_at: int, item_key: str | None = None,
                          instance_id: int | None = None, qty: int | None = None) -> int:
    cur = await conn.execute(
        "INSERT INTO auctions("
        "seller_id, kind, item_key, instance_id, qty, start_price, buyout, "
        "current_bid, current_bidder, end_at, extend_count, created_at, status"
        ") VALUES(?,?,?,?,?,?,?,NULL,NULL,?,0,?,?)",
        (seller_id, kind, item_key, instance_id, qty, int(start_price),
         int(buyout) if buyout is not None else None, int(end_at),
         int(end_at) - CFG.AUCTION_DURATION_SECONDS, CFG.STATUS_ACTIVE))
    auction_id = cur.lastrowid
    await cur.close()
    return int(auction_id)


async def create_equipment_auction(seller_id: int, instance_id: int, start_price: int,
                                   buyout: int | None = None, now: int = None) -> dict:
    """法宝实例挂拍：实扣挂拍费，并把实例托管为 auction 状态。"""
    now = _now(now)
    start_price = int(start_price)
    buyout = int(buyout) if buyout is not None else None
    if start_price <= 0:
        return {"status": "bad_request"}
    if err := _validate_buyout(start_price, buyout):
        return err
    async with db.transaction() as conn:
        lookup = await character.item_instance_for_action_conn(conn, seller_id, instance_id)
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        if not equipment_slot(inst["base_key"]):
            return {"status": "not_equipment"}
        if inst["equipped_slot"]:
            return {"status": "equipped"}
        floor = CFG.floor_price_for_tier(inst["tier"])
        if err := _validate_start_price(start_price, floor):
            return err
        if await _active_count(conn, seller_id) >= CFG.MAX_ACTIVE_AUCTIONS_PER_SELLER:
            return {"status": "too_many"}
        fee = await _listing_fee_quote(conn, seller_id, start_price)
        if fee["status"] != "ok":
            return fee
        cur = await conn.execute(
            "UPDATE item_instances SET status=? "
            "WHERE id=? AND user_id=? AND equipped_slot IS NULL AND status=?",
            (CFG.INSTANCE_STATUS_AUCTION, instance_id, seller_id, CFG.INSTANCE_STATUS_NORMAL))
        changed = cur.rowcount
        await cur.close()
        if not changed:
            return {"status": "locked"}
        await _charge_listing_fee(conn, seller_id, fee["fee"])
        end_at = now + CFG.AUCTION_DURATION_SECONDS
        auction_id = await _insert_auction(
            conn, seller_id, CFG.KIND_EQUIPMENT, start_price, buyout, end_at,
            item_key=inst["base_key"], instance_id=instance_id, qty=1)
        return {"status": "ok", "auction_id": auction_id, "kind": CFG.KIND_EQUIPMENT,
                "item": item_name(inst["base_key"]), "instance_id": instance_id,
                "start_price": start_price, "buyout": buyout, "fee": fee["fee"],
                "end_at": end_at}


async def create_material_auction(seller_id: int, item_key: str, qty: int, start_price: int,
                                  buyout: int | None = None, now: int = None) -> dict:
    """白名单材料挂拍：沿用坊市模型，上架即扣非绑定库存。"""
    now = _now(now)
    qty = int(qty)
    start_price = int(start_price)
    buyout = int(buyout) if buyout is not None else None
    if qty <= 0 or start_price <= 0:
        return {"status": "bad_request"}
    if item_key not in CFG.MATERIAL_WHITELIST or not is_tradable(item_key):
        return {"status": "no_trade", "item": item_name(item_key)}
    floor = max(CFG.DEFAULT_SYSTEM_FLOOR_PRICE, int(ITEMS.get(item_key, {}).get("sell", 0) or 0))
    if err := _validate_start_price(start_price, floor):
        return err
    if err := _validate_buyout(start_price, buyout):
        return err
    async with db.transaction() as conn:
        if await _active_count(conn, seller_id) >= CFG.MAX_ACTIVE_AUCTIONS_PER_SELLER:
            return {"status": "too_many"}
        have = await character.item_qty_conn(conn, seller_id, item_key, bound=0)
        if have < qty:
            return {"status": "no_item", "have": have}
        fee = await _listing_fee_quote(conn, seller_id, start_price)
        if fee["status"] != "ok":
            return fee
        await character.consume_item_conn(conn, seller_id, item_key, qty, bound=0)
        await _charge_listing_fee(conn, seller_id, fee["fee"])
        end_at = now + CFG.AUCTION_DURATION_SECONDS
        auction_id = await _insert_auction(
            conn, seller_id, CFG.KIND_MATERIAL, start_price, buyout, end_at,
            item_key=item_key, qty=qty)
        return {"status": "ok", "auction_id": auction_id, "kind": CFG.KIND_MATERIAL,
                "item": item_name(item_key), "qty": qty, "start_price": start_price,
                "buyout": buyout, "fee": fee["fee"], "end_at": end_at}


async def cancel(seller_id: int, auction_id: int, now: int = None) -> dict:
    """无人出价时撤拍；挂拍费不退，托管物退回。"""
    now = _now(now)
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM auctions WHERE id=?", (auction_id,))
        auction = await cur.fetchone()
        await cur.close()
        if not auction or auction["status"] != CFG.STATUS_ACTIVE:
            return {"status": "not_available"}
        if auction["seller_id"] != seller_id:
            return {"status": "forbidden"}
        if auction["current_bidder"] is not None or auction["current_bid"] is not None:
            return {"status": "has_bid"}
        cur = await conn.execute(
            "UPDATE auctions SET status=?, settled_at=? WHERE id=? AND status=?",
            (CFG.STATUS_CANCELLED, int(now), auction_id, CFG.STATUS_ACTIVE))
        changed = cur.rowcount
        await cur.close()
        if not changed:
            return {"status": "not_available"}
        if auction["kind"] == CFG.KIND_EQUIPMENT:
            await conn.execute(
                "UPDATE item_instances SET status=? WHERE id=? AND user_id=?",
                (CFG.INSTANCE_STATUS_NORMAL, auction["instance_id"], seller_id))
            return {"status": "ok", "kind": CFG.KIND_EQUIPMENT, "auction_id": auction_id,
                    "item": item_name(auction["item_key"])}
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty=qty+?",
            (seller_id, auction["item_key"], auction["qty"], auction["qty"]))
        return {"status": "ok", "kind": CFG.KIND_MATERIAL, "auction_id": auction_id,
                "item": item_name(auction["item_key"]), "qty": auction["qty"]}


async def list_active(limit: int = 20) -> list[dict]:
    """拍卖行首页清单：按快结拍优先展示 active 拍卖。"""
    rows = await db.fetchall(
        "SELECT * FROM auctions WHERE status=? ORDER BY end_at, id LIMIT ?",
        (CFG.STATUS_ACTIVE, int(limit)))
    return [_format_auction(row) for row in rows]


async def watch(user_id: int, auction_id: int, now: int = None) -> dict:
    """关注一场拍卖：后续被超价、临近结拍会进入私聊通知队列。"""
    now = _now(now)
    async with db.transaction() as conn:
        auction = await _auction_row_conn(conn, auction_id)
        if not auction or auction["status"] != CFG.STATUS_ACTIVE:
            return {"status": "not_available"}
        if auction["seller_id"] == user_id:
            return {"status": "self_watch"}
        await _ensure_watcher(conn, auction_id, user_id, now)
        return {"status": "ok", "auction_id": auction_id,
                "item": item_name(auction["item_key"])}


async def unwatch(user_id: int, auction_id: int) -> dict:
    async with db.transaction() as conn:
        cur = await conn.execute(
            "DELETE FROM auction_watchers WHERE auction_id=? AND user_id=?",
            (auction_id, user_id))
        changed = cur.rowcount
        await cur.close()
    return {"status": "ok" if changed else "not_watching", "auction_id": auction_id}


async def is_watching(user_id: int, auction_id: int) -> bool:
    row = await db.fetchone(
        "SELECT 1 FROM auction_watchers WHERE auction_id=? AND user_id=?",
        (auction_id, user_id))
    return row is not None


async def _auction_row_conn(conn, auction_id: int):
    cur = await conn.execute("SELECT * FROM auctions WHERE id=?", (auction_id,))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _ensure_watcher(conn, auction_id: int, user_id: int, now: int) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO auction_watchers(auction_id, user_id, created_at) "
        "VALUES(?,?,?)",
        (auction_id, user_id, int(now)))


async def _is_watcher_conn(conn, auction_id: int, user_id: int) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM auction_watchers WHERE auction_id=? AND user_id=?",
        (auction_id, user_id))
    row = await cur.fetchone()
    await cur.close()
    return row is not None


async def _queue_outbid_notice(conn, auction, user_id: int, old_bid: int, new_bid: int,
                               now: int) -> None:
    if not await _is_watcher_conn(conn, auction["id"], user_id):
        return
    await social.queue_from_event_conn(
        conn, user_id, "auction.outbid",
        {"auction_id": auction["id"], "item": item_name(auction["item_key"]),
         "old_bid": int(old_bid), "new_bid": int(new_bid)},
        now)
    await conn.execute(
        "UPDATE auction_watchers SET outbid_notified_at=? WHERE auction_id=? AND user_id=?",
        (int(now), auction["id"], user_id))


async def notify_recent_auctions(bot, now: int = None) -> dict:
    """每小时向已知群汇总新上拍的拍卖；无新拍则静默。"""
    now = _now(now)
    chats = await db.fetchall("SELECT chat_id FROM bot_chats ORDER BY last_seen_at DESC")
    sent = failed = skipped = auctions = 0
    for chat in chats:
        res = await _notify_recent_auctions_for_chat(bot, chat["chat_id"], now)
        if res["status"] == "sent":
            sent += 1
            auctions += res["auctions"]
        elif res["status"] == "failed":
            failed += 1
        else:
            skipped += 1
    return {"sent": sent, "failed": failed, "skipped": skipped, "auctions": auctions}


async def _notify_recent_auctions_for_chat(bot, chat_id: int, now: int) -> dict:
    since = await _last_auction_broadcast_at(chat_id, now)
    rows = await _new_active_auctions(since, now, CFG.AUCTION_BROADCAST_LIMIT)
    total = await _new_active_auction_count(since, now)
    if total <= 0:
        await _remember_auction_broadcast(chat_id, now)
        return {"status": "skipped", "auctions": 0}
    text = _recent_auctions_text(rows, total)
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:
        log.warning("auction broadcast send failed chat_id=%s auctions=%s: %s",
                    chat_id, total, exc)
        await _remember_auction_broadcast(chat_id, now)
        return {"status": "failed", "auctions": total}
    await _remember_auction_broadcast(chat_id, now)
    return {"status": "sent", "auctions": total}


async def _last_auction_broadcast_at(chat_id: int, now: int) -> int:
    row = await db.fetchone(
        "SELECT last_new_notified_at FROM auction_broadcast_state WHERE chat_id=?",
        (chat_id,))
    if row:
        return int(row["last_new_notified_at"])
    return now - CFG.AUCTION_BROADCAST_WINDOW_SECONDS - 1


async def _remember_auction_broadcast(chat_id: int, now: int) -> None:
    await db.execute(
        "INSERT INTO auction_broadcast_state(chat_id, last_new_notified_at) VALUES(?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET last_new_notified_at=?",
        (chat_id, int(now), int(now)))


async def _new_active_auctions(since: int, now: int, limit: int) -> list[dict]:
    rows = await db.fetchall(
        "SELECT a.*, u.username FROM auctions a "
        "LEFT JOIN users u ON u.tg_user_id=a.seller_id "
        "WHERE a.status=? AND a.created_at>? AND a.created_at<=? "
        "ORDER BY a.created_at, a.id LIMIT ?",
        (CFG.STATUS_ACTIVE, int(since), int(now), int(limit)))
    return [dict(row) for row in rows]


async def _new_active_auction_count(since: int, now: int) -> int:
    row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM auctions "
        "WHERE status=? AND created_at>? AND created_at<=?",
        (CFG.STATUS_ACTIVE, int(since), int(now)))
    return int(row["n"] or 0)


def _recent_auctions_text(rows: list[dict], total: int) -> str:
    lines = ["🔨 拍卖行上新", f"本轮有 {total} 场新拍："]
    for idx, row in enumerate(rows, start=1):
        seller = row.get("username") or f"道友{row['seller_id']}"
        lines.append(
            f"{idx}. #{row['id']} {item_name(row['item_key'])}×{row['qty'] or 1} "
            f"· 起拍 {row['start_price']}灵石 · {seller}")
    if total > len(rows):
        lines.append(f"另有 {total - len(rows)} 场可在 /auction 查看。")
    lines.append("发送 /auction 查看和关注。")
    return "\n".join(lines)


async def notify_closing_auctions(bot, now: int = None) -> dict:
    """向已知群推送临近结拍的拍卖，每场每群只推一次。"""
    now = _now(now)
    chats = await db.fetchall("SELECT chat_id FROM bot_chats ORDER BY last_seen_at DESC")
    sent = failed = skipped = auctions = 0
    for chat in chats:
        res = await _notify_closing_auctions_for_chat(bot, chat["chat_id"], now)
        if res["status"] == "sent":
            sent += 1
            auctions += res["auctions"]
        elif res["status"] == "failed":
            failed += 1
        else:
            skipped += 1
    return {"sent": sent, "failed": failed, "skipped": skipped, "auctions": auctions}


async def _notify_closing_auctions_for_chat(bot, chat_id: int, now: int) -> dict:
    rows = await _closing_auctions_for_chat(chat_id, now, CFG.AUCTION_BROADCAST_LIMIT)
    if not rows:
        return {"status": "skipped", "auctions": 0}
    text = _closing_auctions_text(rows, now)
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:
        log.warning("auction closing broadcast failed chat_id=%s auctions=%s: %s",
                    chat_id, len(rows), exc)
        await _remember_closing_broadcasts(chat_id, rows, now)
        return {"status": "failed", "auctions": len(rows)}
    await _remember_closing_broadcasts(chat_id, rows, now)
    return {"status": "sent", "auctions": len(rows)}


async def _closing_auctions_for_chat(chat_id: int, now: int, limit: int) -> list[dict]:
    rows = await db.fetchall(
        "SELECT a.* FROM auctions a "
        "LEFT JOIN auction_closing_broadcasts b "
        "ON b.chat_id=? AND b.auction_id=a.id "
        "WHERE a.status=? AND a.end_at>? AND a.end_at<=? "
        "AND b.auction_id IS NULL "
        "ORDER BY a.end_at, a.id LIMIT ?",
        (chat_id, CFG.STATUS_ACTIVE, int(now),
         int(now) + CFG.CLOSING_NOTICE_WINDOW_SECONDS, int(limit)))
    return [dict(row) for row in rows]


async def _remember_closing_broadcasts(chat_id: int, rows: list[dict], now: int) -> None:
    async with db.transaction() as conn:
        for row in rows:
            await conn.execute(
                "INSERT OR IGNORE INTO auction_closing_broadcasts(chat_id, auction_id, notified_at) "
                "VALUES(?,?,?)",
                (chat_id, row["id"], int(now)))


def _closing_auctions_text(rows: list[dict], now: int) -> str:
    lines = ["⏳ 拍卖将结", "以下拍卖一炷香内收槌："]
    for idx, row in enumerate(rows, start=1):
        minutes = max(1, int((row["end_at"] - now + 59) // 60))
        price = row["current_bid"] if row["current_bid"] is not None else row["start_price"]
        lines.append(
            f"{idx}. #{row['id']} {item_name(row['item_key'])}×{row['qty'] or 1} "
            f"· 当前 {price}灵石 · 约 {minutes} 分钟")
    lines.append("发送 /auction 查看。")
    return "\n".join(lines)


async def notify_closing_watchers(now: int = None) -> dict:
    """给关注者推送临近结拍私聊，写入社交通知队列后由 flush_broadcasts 发送。"""
    now = _now(now)
    rows = await db.fetchall(
        "SELECT w.auction_id, w.user_id, a.item_key, a.current_bid, a.start_price, a.end_at "
        "FROM auction_watchers w "
        "JOIN auctions a ON a.id=w.auction_id "
        "WHERE a.status=? AND a.end_at>? AND a.end_at<=? "
        "AND w.closing_notified_at IS NULL "
        "ORDER BY a.end_at, a.id LIMIT ?",
        (CFG.STATUS_ACTIVE, int(now), int(now) + CFG.CLOSING_NOTICE_WINDOW_SECONDS,
         CFG.WATCHER_NOTIFY_LIMIT))
    queued = 0
    async with db.transaction() as conn:
        for row in rows:
            price = row["current_bid"] if row["current_bid"] is not None else row["start_price"]
            await social.queue_from_event_conn(
                conn, row["user_id"], "auction.closing",
                {"auction_id": row["auction_id"], "item": item_name(row["item_key"]),
                 "price": int(price), "minutes": max(1, int((row["end_at"] - now + 59) // 60))},
                now)
            await conn.execute(
                "UPDATE auction_watchers SET closing_notified_at=? "
                "WHERE auction_id=? AND user_id=?",
                (int(now), row["auction_id"], row["user_id"]))
            queued += 1
    return {"status": "ok", "queued": queued}


async def audit_suspicious(limit_price: int = CFG.HIGH_PRICE_BROADCAST_THRESHOLD) -> list[dict]:
    """高价可疑记录：在拍高价与已成交天价都进入审计视野。"""
    limit_price = int(limit_price)
    active_rows = await db.fetchall(
        "SELECT * FROM auctions "
        "WHERE status=? AND (start_price>=? OR buyout>=? OR current_bid>=?)",
        (CFG.STATUS_ACTIVE, limit_price, limit_price, limit_price))
    sold_rows = await db.fetchall(
        "SELECT * FROM auctions WHERE status=? AND current_bid>=?",
        (CFG.STATUS_SOLD, limit_price))
    results = []
    for row in active_rows:
        results.append(_format_audit_auction(row, "active", limit_price))
    for row in sold_rows:
        results.append(_format_audit_auction(row, "sold", limit_price))
    results.sort(key=lambda r: (r["price"], r["auction_id"]), reverse=True)
    return results


async def audit_frequent_trades(now: int = None,
                                window_seconds: int = CFG.AUDIT_FREQUENT_WINDOW_SECONDS,
                                min_trades: int = CFG.AUDIT_FREQUENT_MIN_TRADES) -> list[dict]:
    """高频对倒：同一卖家/买家对子在窗口内多次成交。"""
    now = _now(now)
    since = now - int(window_seconds)
    rows = await db.fetchall(
        "SELECT seller_id, current_bidder AS buyer_id, COUNT(*) AS trades, "
        "SUM(current_bid) AS total_price, MIN(settled_at) AS first_at, "
        "MAX(settled_at) AS last_at "
        "FROM auctions "
        "WHERE status=? AND current_bidder IS NOT NULL AND settled_at>? AND settled_at<=? "
        "GROUP BY seller_id, current_bidder HAVING trades>=? "
        "ORDER BY trades DESC, total_price DESC",
        (CFG.STATUS_SOLD, since, now, int(min_trades)))
    return [dict(row) for row in rows]


async def audit_report(limit_price: int = CFG.HIGH_PRICE_BROADCAST_THRESHOLD,
                       now: int = None,
                       window_seconds: int = CFG.AUDIT_FREQUENT_WINDOW_SECONDS,
                       min_trades: int = CFG.AUDIT_FREQUENT_MIN_TRADES) -> dict:
    """拍卖行审计总览，供离线工具和上线巡检读取。"""
    return {
        "high_price": await audit_suspicious(limit_price),
        "frequent_trades": await audit_frequent_trades(
            now=now, window_seconds=window_seconds, min_trades=min_trades),
    }


def _min_bid(auction) -> int:
    if auction["current_bid"] is None:
        return int(auction["start_price"])
    return CFG.min_next_bid(int(auction["current_bid"]))


def _maybe_extend_end_at(auction, now: int) -> tuple[int, int, bool]:
    end_at = int(auction["end_at"])
    extend_count = int(auction["extend_count"] or 0)
    if 0 < end_at - now <= CFG.SNIPE_WINDOW_SECONDS and extend_count < CFG.SNIPE_MAX_EXTENSIONS:
        return end_at + CFG.SNIPE_EXTEND_SECONDS, extend_count + 1, True
    return end_at, extend_count, False


async def _complete_sale(conn, auction, buyer_id: int, price: int, now: int,
                         require_escrow: bool = False) -> dict:
    tax = int(price * CFG.AUCTION_TAX_RATE)
    seller_gain = price - tax
    if require_escrow:
        escrow = await _escrow_amount(conn, auction["id"], buyer_id)
        if escrow < price:
            return {"status": "bad_escrow", "need": price, "have": escrow}
    cur = await conn.execute(
        "UPDATE auctions SET current_bid=?, current_bidder=?, status=?, settled_at=? "
        "WHERE id=? AND status=?",
        (int(price), buyer_id, CFG.STATUS_SOLD, int(now), auction["id"], CFG.STATUS_ACTIVE))
    changed = cur.rowcount
    await cur.close()
    if not changed:
        return {"status": "not_available"}
    if auction["kind"] == CFG.KIND_EQUIPMENT:
        await conn.execute(
            "UPDATE item_instances SET user_id=?, equipped_slot=NULL, status=? WHERE id=?",
            (buyer_id, CFG.INSTANCE_STATUS_NORMAL, auction["instance_id"]))
    else:
        await _add_item(conn, buyer_id, auction["item_key"], auction["qty"])
    await _refund_stone(conn, auction["seller_id"], seller_gain)
    await _clear_escrow(conn, auction["id"])
    await game_events.emit_conn(
        conn, buyer_id, "auction.sold",
        {"auction_id": auction["id"], "seller_id": auction["seller_id"],
         "item": item_name(auction["item_key"]), "price": int(price), "tax": tax},
        now)
    if int(price) >= CFG.HIGH_PRICE_BROADCAST_THRESHOLD:
        await game_events.emit_conn(
            conn, buyer_id, "auction.high_price_sale",
            {"auction_id": auction["id"], "seller_id": auction["seller_id"],
             "item": item_name(auction["item_key"]), "qty": auction["qty"],
             "price": int(price)},
            now)
    return {"status": "ok", "sold": True, "auction_id": auction["id"],
            "kind": auction["kind"], "item": item_name(auction["item_key"]),
            "qty": auction["qty"], "price": int(price), "tax": tax,
            "seller_gain": seller_gain, "buyer_id": buyer_id}


async def bid(bidder_id: int, auction_id: int, amount: int, now: int = None) -> dict:
    """出价实扣灵石入 escrow；达到 buyout 时立即成交。"""
    now = _now(now)
    amount = int(amount)
    if amount <= 0:
        return {"status": "bad_request"}
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM auctions WHERE id=?", (auction_id,))
        auction = await cur.fetchone()
        await cur.close()
        if not auction or auction["status"] != CFG.STATUS_ACTIVE or int(auction["end_at"]) <= now:
            return {"status": "not_available"}
        if auction["seller_id"] == bidder_id:
            return {"status": "self_bid"}

        current_bid = int(auction["current_bid"] or 0)
        current_bidder = auction["current_bidder"]
        buyout = auction["buyout"]
        if buyout is not None and amount >= int(buyout):
            price = int(buyout)
            existing = current_bid if current_bidder == bidder_id else 0
            charge = price - existing
            pay = await _charge_stone(conn, bidder_id, charge)
            if pay["status"] != "ok":
                return pay
            if current_bidder is not None and current_bidder != bidder_id:
                await _refund_stone(conn, current_bidder, current_bid)
            await _record_bid(conn, auction_id, bidder_id, price, now)
            sold = await _complete_sale(conn, auction, bidder_id, price, now)
            if sold["status"] == "ok":
                await _ensure_watcher(conn, auction_id, bidder_id, now)
                if current_bidder is not None and current_bidder != bidder_id:
                    await _queue_outbid_notice(conn, auction, current_bidder, current_bid, price, now)
            return sold if sold["status"] != "ok" else {
                **sold, "buyout": True, "paid": price, "refunded_bidder": current_bidder
                if current_bidder != bidder_id else None,
            }

        minimum = _min_bid(auction)
        if amount < minimum:
            return {"status": "bid_too_low", "min_bid": minimum}

        if current_bidder == bidder_id:
            charge = amount - current_bid
            pay = await _charge_stone(conn, bidder_id, charge)
            if pay["status"] != "ok":
                return pay
            await _set_escrow(conn, auction_id, bidder_id, amount)
        else:
            pay = await _charge_stone(conn, bidder_id, amount)
            if pay["status"] != "ok":
                return pay
            if current_bidder is not None:
                await _refund_stone(conn, current_bidder, current_bid)
                await _clear_escrow(conn, auction_id, current_bidder)
            await _set_escrow(conn, auction_id, bidder_id, amount)

        new_end_at, extend_count, extended = _maybe_extend_end_at(auction, now)
        cur = await conn.execute(
            "UPDATE auctions SET current_bid=?, current_bidder=?, end_at=?, extend_count=? "
            "WHERE id=? AND status=?",
            (amount, bidder_id, new_end_at, extend_count, auction_id, CFG.STATUS_ACTIVE))
        changed = cur.rowcount
        await cur.close()
        if not changed:
            return {"status": "not_available"}
        await _record_bid(conn, auction_id, bidder_id, amount, now)
        await _ensure_watcher(conn, auction_id, bidder_id, now)
        if current_bidder is not None and current_bidder != bidder_id:
            await _queue_outbid_notice(conn, auction, current_bidder, current_bid, amount, now)
        return {"status": "ok", "auction_id": auction_id, "bid": amount,
                "bidder_id": bidder_id, "min_next_bid": CFG.min_next_bid(amount),
                "end_at": new_end_at, "extended": extended,
                "extend_count": extend_count}


async def settle(auction_id: int, now: int = None) -> dict:
    """结算单场到期拍卖；重复调用只返回 no-op，不重复发货发钱。"""
    now = _now(now)
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM auctions WHERE id=?", (auction_id,))
        auction = await cur.fetchone()
        await cur.close()
        if not auction:
            return {"status": "not_found"}
        if auction["status"] != CFG.STATUS_ACTIVE:
            return {"status": "noop", "auction_id": auction_id, "final_status": auction["status"]}
        if int(auction["end_at"]) > now:
            return {"status": "not_due", "auction_id": auction_id, "end_at": int(auction["end_at"])}

        if auction["current_bidder"] is None or auction["current_bid"] is None:
            cur = await conn.execute(
                "UPDATE auctions SET status=?, settled_at=? WHERE id=? AND status=?",
                (CFG.STATUS_PASSED, int(now), auction_id, CFG.STATUS_ACTIVE))
            changed = cur.rowcount
            await cur.close()
            if not changed:
                return {"status": "noop", "auction_id": auction_id, "final_status": CFG.STATUS_PASSED}
            await _return_lot(conn, auction)
            refunded = await _refund_all_escrow(conn, auction_id)
            return {"status": "ok", "result": CFG.STATUS_PASSED, "auction_id": auction_id,
                    "kind": auction["kind"], "item": item_name(auction["item_key"]),
                    "qty": auction["qty"], "refunded": refunded}

        sold = await _complete_sale(
            conn, auction, auction["current_bidder"], int(auction["current_bid"]),
            now, require_escrow=True)
        return sold if sold["status"] != "ok" else {**sold, "result": CFG.STATUS_SOLD}


async def settle_due(now: int = None, limit: int = 20) -> dict:
    """扫描并结算到期 active 拍卖，供 APScheduler 每分钟调用。"""
    now = _now(now)
    rows = await db.fetchall(
        "SELECT id FROM auctions WHERE status=? AND end_at<=? ORDER BY end_at, id LIMIT ?",
        (CFG.STATUS_ACTIVE, now, int(limit)))
    results = []
    for row in rows:
        results.append(await settle(row["id"], now=now))
    return {"status": "ok", "checked": len(rows),
            "settled": sum(1 for r in results if r.get("status") == "ok"),
            "results": results}


async def get_auction(auction_id: int) -> dict | None:
    row = await db.fetchone("SELECT * FROM auctions WHERE id=?", (auction_id,))
    return dict(row) if row else None


def _format_auction(row) -> dict:
    return {
        "id": row["id"],
        "seller_id": row["seller_id"],
        "kind": row["kind"],
        "item_key": row["item_key"],
        "item": item_name(row["item_key"]),
        "instance_id": row["instance_id"],
        "qty": row["qty"],
        "start_price": row["start_price"],
        "buyout": row["buyout"],
        "current_bid": row["current_bid"],
        "current_bidder": row["current_bidder"],
        "end_at": row["end_at"],
        "extend_count": row["extend_count"],
        "created_at": row["created_at"],
        "settled_at": row["settled_at"],
        "status": row["status"],
    }


def _format_audit_auction(row, source: str, limit_price: int) -> dict:
    prices = {
        "start_price": int(row["start_price"] or 0),
        "buyout": int(row["buyout"] or 0),
        "current_bid": int(row["current_bid"] or 0),
    }
    price_kind, price = max(prices.items(), key=lambda item: item[1])
    if source == "sold":
        price_kind = "current_bid"
        price = int(row["current_bid"] or 0)
    return {
        "auction_id": row["id"],
        "source": source,
        "price_kind": price_kind,
        "price": price,
        "threshold": int(limit_price),
        "seller_id": row["seller_id"],
        "buyer_id": row["current_bidder"],
        "kind": row["kind"],
        "item_key": row["item_key"],
        "item": item_name(row["item_key"]),
        "qty": row["qty"],
        "status": row["status"],
        "created_at": row["created_at"],
        "settled_at": row["settled_at"],
    }
