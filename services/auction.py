from __future__ import annotations

"""英式拍卖行服务：挂拍、托管与撤拍（spec-v3 §6 / M2）。"""

import time

from config import auction as CFG
from config.items import ITEMS, equipment_slot, is_tradable, item_name
from models import db
from services import character


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


async def get_auction(auction_id: int) -> dict | None:
    row = await db.fetchone("SELECT * FROM auctions WHERE id=?", (auction_id,))
    return dict(row) if row else None
