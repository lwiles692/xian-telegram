from __future__ import annotations

import pytest
import pytest_asyncio

from config import auction as AUCTION
from config.items import NO_TRADE
from models import db
from services import auction, character
from tools import balance_sim as B


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "auction.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _create_instance(user_id: int, base_key: str = "玄铁剑") -> int:
    await character.create_item_instance(user_id, base_key)
    row = await db.fetchone(
        "SELECT id FROM item_instances WHERE user_id=? AND base_key=? ORDER BY id DESC LIMIT 1",
        (user_id, base_key))
    return row["id"]


@pytest.mark.asyncio
async def test_auction_schema_and_instance_status_migration_are_idempotent(tmp_path):
    path = str(tmp_path / "auction-schema.db")
    await db.init_db(path)
    await db.init_db(path)
    try:
        auction_cols = await db.fetchall("PRAGMA table_info(auctions)")
        bid_cols = await db.fetchall("PRAGMA table_info(auction_bids)")
        escrow_cols = await db.fetchall("PRAGMA table_info(auction_escrow)")
        inst_cols = await db.fetchall("PRAGMA table_info(item_instances)")
        indexes = await db.fetchall("PRAGMA index_list(auctions)")
        bid_indexes = await db.fetchall("PRAGMA index_list(auction_bids)")
    finally:
        await db.close_db()

    assert {row["name"] for row in auction_cols} >= {
        "id", "seller_id", "kind", "item_key", "instance_id", "qty",
        "start_price", "buyout", "current_bid", "current_bidder",
        "end_at", "extend_count", "status",
    }
    assert {row["name"] for row in bid_cols} == {"id", "auction_id", "bidder_id", "amount", "bid_at"}
    assert {row["name"] for row in escrow_cols} == {"auction_id", "bidder_id", "amount"}
    assert "status" in {row["name"] for row in inst_cols}
    assert {"idx_auctions_status_end", "idx_auctions_seller"} <= {row["name"] for row in indexes}
    assert "idx_auction_bids_auction" in {row["name"] for row in bid_indexes}


@pytest.mark.asyncio
async def test_item_instance_status_defaults_to_normal(temp_db):
    uid = 7201
    await character.create(uid, "拍卖器主")
    await character.create_item_instance(uid, "玄铁剑")

    row = await db.fetchone("SELECT status FROM item_instances WHERE user_id=? AND base_key=?", (uid, "玄铁剑"))

    assert row["status"] == AUCTION.INSTANCE_STATUS_NORMAL


def test_auction_config_matches_m2_initial_rules():
    assert AUCTION.AUCTION_DURATION_SECONDS == 24 * 3600
    assert AUCTION.MIN_BID_INCREMENT_PCT == 0.05
    assert AUCTION.SNIPE_WINDOW_SECONDS == 5 * 60
    assert AUCTION.SNIPE_EXTEND_SECONDS == 5 * 60
    assert AUCTION.SNIPE_MAX_EXTENSIONS == 6
    assert AUCTION.LISTING_FEE_RATE == 0.01
    assert AUCTION.AUCTION_TAX_RATE == 0.10
    assert AUCTION.MAX_ACTIVE_AUCTIONS_PER_SELLER == 3
    assert AUCTION.BUYOUT_MIN_MULTIPLIER == 1.20
    assert AUCTION.min_buyout_price(100) == 120
    assert AUCTION.listing_fee(1) == 1
    assert AUCTION.min_next_bid(100) == 105
    assert AUCTION.floor_price_for_tier("玄") > AUCTION.floor_price_for_tier("宝")


def test_auction_material_whitelist_is_tradeable_and_shared_with_balance_sim():
    assert {"天外残玉", "混沌残核"} <= AUCTION.MATERIAL_WHITELIST
    assert AUCTION.MATERIAL_WHITELIST.isdisjoint(NO_TRADE)
    assert B.AUCTION_WHITELIST_MATERIALS == AUCTION.MATERIAL_WHITELIST
    assert B.WHITELIST_MARKET_VALUE_MULTIPLIER == AUCTION.MATERIAL_MARKET_VALUE_MULTIPLIER


@pytest.mark.asyncio
async def test_equipment_auction_locks_instance_and_charges_fee(temp_db):
    uid = 7210
    await character.create(uid, "挂剑修士")
    await character.add_stone(uid, 1000)
    inst_id = await _create_instance(uid, "玄铁剑")
    before_stone = (await character.get(uid)).spirit_stone

    res = await auction.create_equipment_auction(uid, inst_id, 500, buyout=700, now=1000)

    assert res["status"] == "ok"
    assert res["kind"] == AUCTION.KIND_EQUIPMENT
    assert res["instance_id"] == inst_id
    assert res["fee"] == AUCTION.listing_fee(500)
    assert res["end_at"] == 1000 + AUCTION.AUCTION_DURATION_SECONDS
    assert (await character.get(uid)).spirit_stone == before_stone - AUCTION.listing_fee(500)

    row = await db.fetchone("SELECT * FROM auctions WHERE id=?", (res["auction_id"],))
    assert row["seller_id"] == uid
    assert row["kind"] == AUCTION.KIND_EQUIPMENT
    assert row["item_key"] == "玄铁剑"
    assert row["instance_id"] == inst_id
    assert row["qty"] == 1
    assert row["start_price"] == 500
    assert row["buyout"] == 700
    assert row["status"] == AUCTION.STATUS_ACTIVE
    assert row["end_at"] == res["end_at"]

    inst = await db.fetchone("SELECT status FROM item_instances WHERE id=?", (inst_id,))
    assert inst["status"] == AUCTION.INSTANCE_STATUS_AUCTION


@pytest.mark.asyncio
async def test_equipped_instance_cannot_be_auctioned(temp_db):
    uid = 7211
    await character.create(uid, "佩剑修士")
    await character.add_stone(uid, 1000)
    inst_id = await _create_instance(uid, "玄铁剑")
    assert (await character.equip_instance(uid, inst_id))["status"] == "ok"
    before_stone = (await character.get(uid)).spirit_stone

    res = await auction.create_equipment_auction(uid, inst_id, 500, now=1000)

    assert res["status"] == "equipped"
    assert (await character.get(uid)).spirit_stone == before_stone
    inst = await db.fetchone("SELECT status FROM item_instances WHERE id=?", (inst_id,))
    assert inst["status"] == AUCTION.INSTANCE_STATUS_NORMAL


@pytest.mark.asyncio
async def test_equipment_auction_rejects_low_price_and_bad_buyout(temp_db):
    uid = 7212
    await character.create(uid, "估价修士")
    await character.add_stone(uid, 1000)
    inst_id = await _create_instance(uid, "玄铁剑")

    low = await auction.create_equipment_auction(uid, inst_id, 199, now=1000)
    bad_buyout = await auction.create_equipment_auction(uid, inst_id, 500, buyout=599, now=1000)

    assert low == {"status": "price_too_low", "floor": AUCTION.floor_price_for_tier("灵")}
    assert bad_buyout == {"status": "bad_buyout", "min_buyout": AUCTION.min_buyout_price(500)}
    rows = await db.fetchall("SELECT * FROM auctions WHERE seller_id=?", (uid,))
    assert rows == []
    inst = await db.fetchone("SELECT status FROM item_instances WHERE id=?", (inst_id,))
    assert inst["status"] == AUCTION.INSTANCE_STATUS_NORMAL


@pytest.mark.asyncio
async def test_material_auction_deducts_unbound_inventory_and_charges_fee(temp_db):
    uid = 7213
    await character.create(uid, "藏玉修士")
    await character.add_stone(uid, 1000)
    await character.add_item(uid, "天外残玉", 3, bound=0)
    before_stone = (await character.get(uid)).spirit_stone

    res = await auction.create_material_auction(uid, "天外残玉", 2, 500, buyout=650, now=2000)

    assert res["status"] == "ok"
    assert res["kind"] == AUCTION.KIND_MATERIAL
    assert res["qty"] == 2
    assert res["fee"] == AUCTION.listing_fee(500)
    assert await character.item_qty(uid, "天外残玉", bound=0) == 1
    assert (await character.get(uid)).spirit_stone == before_stone - AUCTION.listing_fee(500)

    row = await db.fetchone("SELECT * FROM auctions WHERE id=?", (res["auction_id"],))
    assert row["kind"] == AUCTION.KIND_MATERIAL
    assert row["item_key"] == "天外残玉"
    assert row["instance_id"] is None
    assert row["qty"] == 2
    assert row["start_price"] == 500
    assert row["buyout"] == 650
    assert row["status"] == AUCTION.STATUS_ACTIVE
    assert row["end_at"] == 2000 + AUCTION.AUCTION_DURATION_SECONDS


@pytest.mark.asyncio
async def test_material_auction_rejects_bound_non_whitelist_and_no_trade_items(temp_db):
    uid = 7214
    await character.create(uid, "禁物修士")
    await character.add_stone(uid, 1000)
    await character.add_item(uid, "天外残玉", 2, bound=1)
    await character.add_item(uid, "炼虚丹", 1, bound=0)

    bound_only = await auction.create_material_auction(uid, "天外残玉", 1, 500, now=1000)
    common_material = await auction.create_material_auction(uid, "灵草", 1, 100, now=1000)
    no_trade = await auction.create_material_auction(uid, "炼虚丹", 1, 1000, now=1000)

    assert bound_only["status"] == "no_item"
    assert common_material["status"] == "no_trade"
    assert no_trade["status"] == "no_trade"
    assert await character.item_qty(uid, "天外残玉", bound=1) == 2
    assert await character.item_qty(uid, "炼虚丹", bound=0) == 1
    rows = await db.fetchall("SELECT * FROM auctions WHERE seller_id=?", (uid,))
    assert rows == []


@pytest.mark.asyncio
async def test_active_auction_limit_blocks_fourth_listing(temp_db):
    uid = 7215
    await character.create(uid, "多宝修士")
    await character.add_stone(uid, 1000)
    await character.add_item(uid, "星陨砂", AUCTION.MAX_ACTIVE_AUCTIONS_PER_SELLER + 1, bound=0)

    for idx in range(AUCTION.MAX_ACTIVE_AUCTIONS_PER_SELLER):
        res = await auction.create_material_auction(uid, "星陨砂", 1, 200 + idx, now=1000 + idx)
        assert res["status"] == "ok"

    blocked = await auction.create_material_auction(uid, "星陨砂", 1, 300, now=2000)

    assert blocked["status"] == "too_many"
    assert await character.item_qty(uid, "星陨砂", bound=0) == 1
    rows = await db.fetchall(
        "SELECT * FROM auctions WHERE seller_id=? AND status=?",
        (uid, AUCTION.STATUS_ACTIVE))
    assert len(rows) == AUCTION.MAX_ACTIVE_AUCTIONS_PER_SELLER


@pytest.mark.asyncio
async def test_cancel_equipment_auction_returns_instance_without_refunding_fee(temp_db):
    uid = 7216
    await character.create(uid, "撤剑修士")
    await character.add_stone(uid, 1000)
    inst_id = await _create_instance(uid, "玄铁剑")
    listed = await auction.create_equipment_auction(uid, inst_id, 500, now=1000)
    after_listing_stone = (await character.get(uid)).spirit_stone

    res = await auction.cancel(uid, listed["auction_id"], now=1001)

    assert res["status"] == "ok"
    assert res["kind"] == AUCTION.KIND_EQUIPMENT
    assert (await character.get(uid)).spirit_stone == after_listing_stone
    inst = await db.fetchone("SELECT status FROM item_instances WHERE id=?", (inst_id,))
    row = await db.fetchone("SELECT status FROM auctions WHERE id=?", (listed["auction_id"],))
    assert inst["status"] == AUCTION.INSTANCE_STATUS_NORMAL
    assert row["status"] == AUCTION.STATUS_CANCELLED
    assert (await auction.cancel(uid, listed["auction_id"], now=1002))["status"] == "not_available"


@pytest.mark.asyncio
async def test_cancel_material_auction_returns_inventory_without_refunding_fee(temp_db):
    uid = 7217
    await character.create(uid, "撤玉修士")
    await character.add_stone(uid, 1000)
    await character.add_item(uid, "混沌残核", 2, bound=0)
    listed = await auction.create_material_auction(uid, "混沌残核", 2, 600, now=1000)
    after_listing_stone = (await character.get(uid)).spirit_stone
    assert await character.item_qty(uid, "混沌残核", bound=0) == 0

    res = await auction.cancel(uid, listed["auction_id"], now=1001)

    assert res["status"] == "ok"
    assert res["kind"] == AUCTION.KIND_MATERIAL
    assert res["qty"] == 2
    assert await character.item_qty(uid, "混沌残核", bound=0) == 2
    assert (await character.get(uid)).spirit_stone == after_listing_stone
    row = await db.fetchone("SELECT status FROM auctions WHERE id=?", (listed["auction_id"],))
    assert row["status"] == AUCTION.STATUS_CANCELLED


@pytest.mark.asyncio
async def test_cancel_rejects_non_owner_and_auctions_with_bid(temp_db):
    seller, other = 7218, 7219
    await character.create(seller, "护拍修士")
    await character.create(other, "旁观修士")
    await character.add_stone(seller, 1000)
    await character.add_item(seller, "天外残玉", 1, bound=0)
    listed = await auction.create_material_auction(seller, "天外残玉", 1, 500, now=1000)

    forbidden = await auction.cancel(other, listed["auction_id"], now=1001)
    await db.execute(
        "UPDATE auctions SET current_bid=?, current_bidder=? WHERE id=?",
        (600, other, listed["auction_id"]))
    has_bid = await auction.cancel(seller, listed["auction_id"], now=1002)

    assert forbidden["status"] == "forbidden"
    assert has_bid["status"] == "has_bid"
    assert await character.item_qty(seller, "天外残玉", bound=0) == 0
    row = await db.fetchone("SELECT status FROM auctions WHERE id=?", (listed["auction_id"],))
    assert row["status"] == AUCTION.STATUS_ACTIVE
