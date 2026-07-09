from __future__ import annotations

"""英式拍卖行服务：挂拍、托管与撤拍（spec-v3 §6 / M2）。"""

import time

from config import auction as CFG
from config.items import ITEMS, equipment_slot, is_tradable, item_name
from models import db
from services import character, game_events


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


async def _add_item(conn, user_id: int, item_key: str, qty: int) -> None:
    await conn.execute(
        "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
        "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty=qty+?",
        (user_id, item_key, int(qty), int(qty)))


async def _insert_auction(conn, seller_id: int, kind: str, start_price: int, buyout: int | None,
                          end_at: int, item_key: str | None = None,
                          instance_id: int | None = None, qty: int | None = None) -> int:
    cur = await conn.execute(
        "INSERT INTO auctions("
        "seller_id, kind, item_key, instance_id, qty, start_price, buyout, "
        "current_bid, current_bidder, end_at, extend_count, status"
        ") VALUES(?,?,?,?,?,?,?,NULL,NULL,?,0,?)",
        (seller_id, kind, item_key, instance_id, qty, int(start_price),
         int(buyout) if buyout is not None else None, int(end_at), CFG.STATUS_ACTIVE))
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
            "UPDATE auctions SET status=? WHERE id=? AND status=?",
            (CFG.STATUS_CANCELLED, auction_id, CFG.STATUS_ACTIVE))
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


async def _complete_sale(conn, auction, buyer_id: int, price: int, now: int) -> dict:
    tax = int(price * CFG.AUCTION_TAX_RATE)
    seller_gain = price - tax
    cur = await conn.execute(
        "UPDATE auctions SET current_bid=?, current_bidder=?, status=? "
        "WHERE id=? AND status=?",
        (int(price), buyer_id, CFG.STATUS_SOLD, auction["id"], CFG.STATUS_ACTIVE))
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
        return {"status": "ok", "auction_id": auction_id, "bid": amount,
                "bidder_id": bidder_id, "min_next_bid": CFG.min_next_bid(amount),
                "end_at": new_end_at, "extended": extended,
                "extend_count": extend_count}


async def get_auction(auction_id: int) -> dict | None:
    row = await db.fetchone("SELECT * FROM auctions WHERE id=?", (auction_id,))
    return dict(row) if row else None
