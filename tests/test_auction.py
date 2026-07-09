from __future__ import annotations

import asyncio
import inspect

import pytest
import pytest_asyncio

from config import auction as AUCTION
from config import equipment as EQUIPMENT
from config.items import NO_TRADE
from models import db
from services import auction, character, equipment
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


async def _create_auction_locked_instance(user_id: int) -> tuple[int, dict]:
    await character.create(user_id, "托管修士")
    await character.add_stone(user_id, 1000)
    inst_id = await _create_instance(user_id, "玄铁剑")
    listed = await auction.create_equipment_auction(user_id, inst_id, 500, now=1000)
    assert listed["status"] == "ok"
    return inst_id, listed


async def _stone_sum(*user_ids: int) -> int:
    total = 0
    for user_id in user_ids:
        total += (await character.get(user_id)).spirit_stone
    return total


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
async def test_auction_locked_instance_cannot_be_equipped(temp_db):
    uid = 7220
    inst_id, _listed = await _create_auction_locked_instance(uid)

    res = await character.equip_instance(uid, inst_id)

    assert res["status"] == "locked"
    inst = await db.fetchone("SELECT equipped_slot, status FROM item_instances WHERE id=?", (inst_id,))
    assert inst["equipped_slot"] is None
    assert inst["status"] == AUCTION.INSTANCE_STATUS_AUCTION


@pytest.mark.asyncio
async def test_auction_locked_instance_cannot_be_enhanced(temp_db):
    uid = 7221
    inst_id, _listed = await _create_auction_locked_instance(uid)
    await character.add_item(uid, EQUIPMENT.QIHUN_KEY, 99)
    before_stone = (await character.get(uid)).spirit_stone

    res = await equipment.enhance(uid, inst_id)

    assert res["status"] == "locked"
    assert (await character.get(uid)).spirit_stone == before_stone
    assert await character.item_qty(uid, EQUIPMENT.QIHUN_KEY) == 99


@pytest.mark.asyncio
async def test_auction_locked_instance_cannot_be_reforged(temp_db):
    uid = 7222
    inst_id, _listed = await _create_auction_locked_instance(uid)
    await character.add_item(uid, EQUIPMENT.QIHUN_KEY, 99)
    before_stone = (await character.get(uid)).spirit_stone

    res = await equipment.reforge(uid, inst_id)

    assert res["status"] == "locked"
    assert (await character.get(uid)).spirit_stone == before_stone
    assert await character.item_qty(uid, EQUIPMENT.QIHUN_KEY) == 99


@pytest.mark.asyncio
async def test_auction_locked_instance_cannot_be_decomposed(temp_db):
    uid = 7223
    inst_id, _listed = await _create_auction_locked_instance(uid)

    res = await equipment.decompose(uid, inst_id)

    assert res["status"] == "locked"
    inst = await db.fetchone("SELECT status FROM item_instances WHERE id=?", (inst_id,))
    assert inst["status"] == AUCTION.INSTANCE_STATUS_AUCTION
    assert await character.item_qty(uid, EQUIPMENT.QIHUN_KEY) == 0


@pytest.mark.asyncio
async def test_auction_locked_instance_cannot_be_listed_again(temp_db):
    uid = 7224
    inst_id, _listed = await _create_auction_locked_instance(uid)
    before_stone = (await character.get(uid)).spirit_stone

    res = await auction.create_equipment_auction(uid, inst_id, 500, now=1001)

    assert res["status"] == "locked"
    assert (await character.get(uid)).spirit_stone == before_stone
    rows = await db.fetchall(
        "SELECT * FROM auctions WHERE seller_id=? AND instance_id=? AND status=?",
        (uid, inst_id, AUCTION.STATUS_ACTIVE))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_auction_locked_instance_action_reader_rejects_future_transfer_paths(temp_db):
    uid = 7225
    inst_id, _listed = await _create_auction_locked_instance(uid)

    async with db.transaction() as conn:
        lookup = await character.item_instance_for_action_conn(conn, uid, inst_id)

    assert lookup == {"status": "locked"}


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


@pytest.mark.asyncio
async def test_bid_deducts_stone_into_escrow_and_blocks_cancel(temp_db):
    seller, bidder = 7230, 7231
    await character.create(seller, "拍主")
    await character.create(bidder, "竞价客")
    await character.add_item(seller, "天外残玉", 1, bound=0)
    await character.add_stone(bidder, 1000)
    listed = await auction.create_material_auction(seller, "天外残玉", 1, 500, now=1000)
    before_bidder = (await character.get(bidder)).spirit_stone

    res = await auction.bid(bidder, listed["auction_id"], 500, now=1001)

    assert res["status"] == "ok"
    assert res["bid"] == 500
    assert res["min_next_bid"] == AUCTION.min_next_bid(500)
    assert (await character.get(bidder)).spirit_stone == before_bidder - 500
    escrow = await db.fetchall("SELECT * FROM auction_escrow WHERE auction_id=?", (listed["auction_id"],))
    bids = await db.fetchall("SELECT * FROM auction_bids WHERE auction_id=?", (listed["auction_id"],))
    row = await auction.get_auction(listed["auction_id"])
    assert [dict(r) for r in escrow] == [{
        "auction_id": listed["auction_id"], "bidder_id": bidder, "amount": 500,
    }]
    assert len(bids) == 1
    assert bids[0]["bidder_id"] == bidder
    assert bids[0]["amount"] == 500
    assert row["current_bid"] == 500
    assert row["current_bidder"] == bidder
    assert (await auction.cancel(seller, listed["auction_id"], now=1002))["status"] == "has_bid"


@pytest.mark.asyncio
async def test_outbid_refunds_previous_bidder_and_replaces_escrow(temp_db):
    seller, first, second = 7232, 7233, 7234
    await character.create(seller, "拍主二")
    await character.create(first, "先出价")
    await character.create(second, "后出价")
    await character.add_item(seller, "天外残玉", 1, bound=0)
    await character.add_stone(first, 1000)
    await character.add_stone(second, 1000)
    listed = await auction.create_material_auction(seller, "天外残玉", 1, 500, now=1000)
    first_before = (await character.get(first)).spirit_stone
    second_before = (await character.get(second)).spirit_stone

    assert (await auction.bid(first, listed["auction_id"], 500, now=1001))["status"] == "ok"
    res = await auction.bid(second, listed["auction_id"], AUCTION.min_next_bid(500), now=1002)

    assert res["status"] == "ok"
    assert (await character.get(first)).spirit_stone == first_before
    assert (await character.get(second)).spirit_stone == second_before - AUCTION.min_next_bid(500)
    escrow = await db.fetchall("SELECT * FROM auction_escrow WHERE auction_id=?", (listed["auction_id"],))
    bids = await db.fetchall("SELECT * FROM auction_bids WHERE auction_id=? ORDER BY id", (listed["auction_id"],))
    assert [dict(r) for r in escrow] == [{
        "auction_id": listed["auction_id"], "bidder_id": second,
        "amount": AUCTION.min_next_bid(500),
    }]
    assert [(row["bidder_id"], row["amount"]) for row in bids] == [
        (first, 500), (second, AUCTION.min_next_bid(500)),
    ]


@pytest.mark.asyncio
async def test_concurrent_bids_leave_single_highest_escrow(temp_db):
    seller, first, second = 7244, 7245, 7246
    await character.create(seller, "并拍主")
    await character.create(first, "并拍一")
    await character.create(second, "并拍二")
    await character.add_item(seller, "天外残玉", 1, bound=0)
    await character.add_stone(first, 1000)
    await character.add_stone(second, 1000)
    listed = await auction.create_material_auction(seller, "天外残玉", 1, 500, now=1000)
    first_before = (await character.get(first)).spirit_stone
    second_before = (await character.get(second)).spirit_stone

    results = await asyncio.gather(
        auction.bid(first, listed["auction_id"], 500, now=1001),
        auction.bid(second, listed["auction_id"], AUCTION.min_next_bid(500), now=1001),
    )

    assert any(res["status"] == "ok" for res in results)
    row = await auction.get_auction(listed["auction_id"])
    escrow = await db.fetchall("SELECT * FROM auction_escrow WHERE auction_id=?", (listed["auction_id"],))
    assert row["current_bid"] == AUCTION.min_next_bid(500)
    assert row["current_bidder"] == second
    assert [dict(r) for r in escrow] == [{
        "auction_id": listed["auction_id"], "bidder_id": second,
        "amount": AUCTION.min_next_bid(500),
    }]
    assert (await character.get(first)).spirit_stone == first_before
    assert (await character.get(second)).spirit_stone == second_before - AUCTION.min_next_bid(500)


@pytest.mark.asyncio
async def test_bid_rejects_self_low_poor_and_expired_attempts(temp_db):
    seller, bidder = 7235, 7236
    await character.create(seller, "拍主三")
    await character.create(bidder, "穷客")
    await character.add_item(seller, "天外残玉", 1, bound=0)
    listed = await auction.create_material_auction(seller, "天外残玉", 1, 500, now=1000)

    assert (await auction.bid(seller, listed["auction_id"], 500, now=1001))["status"] == "self_bid"
    low = await auction.bid(bidder, listed["auction_id"], 499, now=1001)
    poor = await auction.bid(bidder, listed["auction_id"], 500, now=1001)
    expired = await auction.bid(bidder, listed["auction_id"], 500,
                                now=1000 + AUCTION.AUCTION_DURATION_SECONDS)

    assert low == {"status": "bid_too_low", "min_bid": 500}
    assert poor["status"] == "no_stone"
    assert poor["need"] == 500
    assert expired["status"] == "not_available"


@pytest.mark.asyncio
async def test_sniping_extends_end_time_at_most_six_times(temp_db):
    seller, bidder = 7237, 7238
    await character.create(seller, "狙拍主")
    await character.create(bidder, "压线客")
    await character.add_item(seller, "天外残玉", 1, bound=0)
    await character.add_stone(bidder, 20_000)
    listed = await auction.create_material_auction(seller, "天外残玉", 1, 500, now=1000)
    await db.execute(
        "UPDATE auctions SET end_at=? WHERE id=?",
        (2000, listed["auction_id"]))

    amount = 500
    end_at = 2000
    for idx in range(AUCTION.SNIPE_MAX_EXTENSIONS + 1):
        amount = amount if idx == 0 else AUCTION.min_next_bid(amount)
        res = await auction.bid(bidder, listed["auction_id"], amount, now=end_at - 1)
        if idx < AUCTION.SNIPE_MAX_EXTENSIONS:
            assert res["extended"] is True
            end_at += AUCTION.SNIPE_EXTEND_SECONDS
        else:
            assert res["extended"] is False
        assert res["end_at"] == end_at

    row = await auction.get_auction(listed["auction_id"])
    assert row["extend_count"] == AUCTION.SNIPE_MAX_EXTENSIONS
    assert row["end_at"] == 2000 + AUCTION.SNIPE_EXTEND_SECONDS * AUCTION.SNIPE_MAX_EXTENSIONS


@pytest.mark.asyncio
async def test_buyout_sells_material_immediately_without_overcharging_or_extending(temp_db):
    seller, buyer = 7239, 7240
    await character.create(seller, "一口价主")
    await character.create(buyer, "一口价客")
    await character.add_item(seller, "混沌残核", 2, bound=0)
    await character.add_stone(buyer, 1000)
    total_before = await _stone_sum(seller, buyer)
    listed = await auction.create_material_auction(seller, "混沌残核", 2, 500, buyout=700, now=1000)
    await db.execute(
        "UPDATE auctions SET end_at=? WHERE id=?",
        (1300, listed["auction_id"]))

    res = await auction.bid(buyer, listed["auction_id"], 900, now=1299)

    assert res["status"] == "ok"
    assert res["sold"] is True
    assert res["buyout"] is True
    assert res["paid"] == 700
    assert res["price"] == 700
    assert res["tax"] == 70
    assert res["seller_gain"] == 630
    assert await character.item_qty(buyer, "混沌残核", bound=0) == 2
    assert (await character.get(buyer)).spirit_stone == 400
    assert await _stone_sum(seller, buyer) == total_before - listed["fee"] - res["tax"]
    row = await auction.get_auction(listed["auction_id"])
    escrow = await db.fetchall("SELECT * FROM auction_escrow WHERE auction_id=?", (listed["auction_id"],))
    bids = await db.fetchall("SELECT * FROM auction_bids WHERE auction_id=?", (listed["auction_id"],))
    assert row["status"] == AUCTION.STATUS_SOLD
    assert row["current_bid"] == 700
    assert row["current_bidder"] == buyer
    assert row["end_at"] == 1300
    assert escrow == []
    assert len(bids) == 1
    assert bids[0]["amount"] == 700


@pytest.mark.asyncio
async def test_buyout_refunds_previous_bidder_and_transfers_equipment(temp_db):
    seller, first, buyer = 7241, 7242, 7243
    await character.create(seller, "卖剑主")
    await character.create(first, "先拍剑")
    await character.create(buyer, "买剑客")
    await character.add_stone(seller, 1000)
    await character.add_stone(first, 1000)
    await character.add_stone(buyer, 1000)
    inst_id = await _create_instance(seller, "玄铁剑")
    total_before = await _stone_sum(seller, first, buyer)
    listed = await auction.create_equipment_auction(seller, inst_id, 500, buyout=700, now=1000)
    first_before = (await character.get(first)).spirit_stone

    assert (await auction.bid(first, listed["auction_id"], 500, now=1001))["status"] == "ok"
    res = await auction.bid(buyer, listed["auction_id"], 1000, now=1002)

    assert res["status"] == "ok"
    assert res["sold"] is True
    assert res["price"] == 700
    assert (await character.get(first)).spirit_stone == first_before
    assert (await character.get(buyer)).spirit_stone == 400
    assert await _stone_sum(seller, first, buyer) == total_before - listed["fee"] - res["tax"]
    inst = await db.fetchone("SELECT user_id, status, equipped_slot FROM item_instances WHERE id=?", (inst_id,))
    escrow = await db.fetchall("SELECT * FROM auction_escrow WHERE auction_id=?", (listed["auction_id"],))
    row = await auction.get_auction(listed["auction_id"])
    assert inst["user_id"] == buyer
    assert inst["status"] == AUCTION.INSTANCE_STATUS_NORMAL
    assert inst["equipped_slot"] is None
    assert row["status"] == AUCTION.STATUS_SOLD
    assert escrow == []


@pytest.mark.asyncio
async def test_settle_passed_material_returns_inventory_and_is_idempotent(temp_db):
    seller = 7247
    await character.create(seller, "流拍主")
    await character.add_item(seller, "天外残玉", 2, bound=0)
    before_stone = (await character.get(seller)).spirit_stone
    listed = await auction.create_material_auction(seller, "天外残玉", 2, 500, now=1000)
    assert await character.item_qty(seller, "天外残玉", bound=0) == 0
    after_listing_stone = (await character.get(seller)).spirit_stone

    early = await auction.settle(listed["auction_id"], now=listed["end_at"] - 1)
    res = await auction.settle(listed["auction_id"], now=listed["end_at"])
    repeat = await auction.settle(listed["auction_id"], now=listed["end_at"] + 1)

    assert early["status"] == "not_due"
    assert res["status"] == "ok"
    assert res["result"] == AUCTION.STATUS_PASSED
    assert repeat["status"] == "noop"
    assert repeat["final_status"] == AUCTION.STATUS_PASSED
    assert await character.item_qty(seller, "天外残玉", bound=0) == 2
    assert (await character.get(seller)).spirit_stone == after_listing_stone
    assert (await character.get(seller)).spirit_stone == before_stone - listed["fee"]
    row = await auction.get_auction(listed["auction_id"])
    assert row["status"] == AUCTION.STATUS_PASSED


@pytest.mark.asyncio
async def test_settle_passed_equipment_restores_instance(temp_db):
    seller = 7248
    await character.create(seller, "流拍剑主")
    inst_id = await _create_instance(seller, "玄铁剑")
    listed = await auction.create_equipment_auction(seller, inst_id, 500, now=1000)

    res = await auction.settle(listed["auction_id"], now=listed["end_at"])

    assert res["status"] == "ok"
    assert res["result"] == AUCTION.STATUS_PASSED
    inst = await db.fetchone("SELECT user_id, status FROM item_instances WHERE id=?", (inst_id,))
    row = await auction.get_auction(listed["auction_id"])
    assert inst["user_id"] == seller
    assert inst["status"] == AUCTION.INSTANCE_STATUS_NORMAL
    assert row["status"] == AUCTION.STATUS_PASSED


@pytest.mark.asyncio
async def test_settle_sold_material_uses_escrow_and_preserves_stone_sinks(temp_db):
    seller, buyer = 7249, 7250
    await character.create(seller, "成交主")
    await character.create(buyer, "成交客")
    await character.add_item(seller, "天外残玉", 1, bound=0)
    await character.add_stone(buyer, 1000)
    total_before = await _stone_sum(seller, buyer)
    listed = await auction.create_material_auction(seller, "天外残玉", 1, 500, now=1000)
    assert (await auction.bid(buyer, listed["auction_id"], 500, now=1001))["status"] == "ok"

    res = await auction.settle(listed["auction_id"], now=listed["end_at"])
    after_once = await _stone_sum(seller, buyer)
    repeat = await auction.settle(listed["auction_id"], now=listed["end_at"] + 1)

    assert res["status"] == "ok"
    assert res["result"] == AUCTION.STATUS_SOLD
    assert res["tax"] == 50
    assert res["seller_gain"] == 450
    assert repeat["status"] == "noop"
    assert await character.item_qty(buyer, "天外残玉", bound=0) == 1
    assert await _stone_sum(seller, buyer) == after_once
    assert after_once == total_before - listed["fee"] - res["tax"]
    escrow = await db.fetchall("SELECT * FROM auction_escrow WHERE auction_id=?", (listed["auction_id"],))
    row = await auction.get_auction(listed["auction_id"])
    assert escrow == []
    assert row["status"] == AUCTION.STATUS_SOLD


@pytest.mark.asyncio
async def test_settle_sold_equipment_transfers_owner_and_is_idempotent(temp_db):
    seller, buyer = 7251, 7252
    await character.create(seller, "成交剑主")
    await character.create(buyer, "成交剑客")
    await character.add_stone(buyer, 1000)
    inst_id = await _create_instance(seller, "玄铁剑")
    total_before = await _stone_sum(seller, buyer)
    listed = await auction.create_equipment_auction(seller, inst_id, 500, now=1000)
    assert (await auction.bid(buyer, listed["auction_id"], 500, now=1001))["status"] == "ok"

    res = await auction.settle(listed["auction_id"], now=listed["end_at"])
    after_once = await _stone_sum(seller, buyer)
    repeat = await auction.settle(listed["auction_id"], now=listed["end_at"] + 1)

    assert res["status"] == "ok"
    assert res["result"] == AUCTION.STATUS_SOLD
    assert repeat["status"] == "noop"
    assert await _stone_sum(seller, buyer) == after_once
    assert after_once == total_before - listed["fee"] - res["tax"]
    inst = await db.fetchone("SELECT user_id, status, equipped_slot FROM item_instances WHERE id=?", (inst_id,))
    assert inst["user_id"] == buyer
    assert inst["status"] == AUCTION.INSTANCE_STATUS_NORMAL
    assert inst["equipped_slot"] is None


@pytest.mark.asyncio
async def test_settle_due_scans_only_due_active_auctions(temp_db):
    due_seller, future_seller = 7253, 7254
    await character.create(due_seller, "到期主")
    await character.create(future_seller, "未到期主")
    await character.add_item(due_seller, "天外残玉", 1, bound=0)
    await character.add_item(future_seller, "天外残玉", 1, bound=0)
    due = await auction.create_material_auction(due_seller, "天外残玉", 1, 500, now=1000)
    future = await auction.create_material_auction(future_seller, "天外残玉", 1, 500, now=2000)

    res = await auction.settle_due(now=due["end_at"], limit=10)

    assert res["status"] == "ok"
    assert res["checked"] == 1
    assert res["settled"] == 1
    assert (await auction.get_auction(due["auction_id"]))["status"] == AUCTION.STATUS_PASSED
    assert (await auction.get_auction(future["auction_id"]))["status"] == AUCTION.STATUS_ACTIVE
    assert await character.item_qty(due_seller, "天外残玉", bound=0) == 1
    assert await character.item_qty(future_seller, "天外残玉", bound=0) == 0


def test_bot_scheduler_registers_auction_settlement():
    from bot import app as bot_app

    source = inspect.getsource(bot_app.main)

    assert "auction_service.settle_due" in source
    assert '"interval", minutes=1' in source
