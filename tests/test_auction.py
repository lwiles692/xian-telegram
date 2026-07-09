from __future__ import annotations

import pytest
import pytest_asyncio

from config import auction as AUCTION
from config.items import NO_TRADE
from models import db
from services import character
from tools import balance_sim as B


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "auction.db"))
    try:
        yield
    finally:
        await db.close_db()


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
