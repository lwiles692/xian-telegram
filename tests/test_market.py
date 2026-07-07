import logging

import pytest
import pytest_asyncio

from models import db
from services import character, market


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "market.db"))
    try:
        yield
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_bound_items_cannot_be_listed(temp_db):
    uid = 9701
    await character.create(uid, "seller")
    await character.add_item(uid, "天魔令", 2, bound=1)

    res = await market.create_listing(uid, "天魔令", 1, 100, now=1000)

    assert res["status"] == "no_item"
    assert await character.item_qty(uid, "天魔令", bound=1) == 2


@pytest.mark.asyncio
async def test_market_buy_transfers_item_stone_and_tax(temp_db):
    seller, buyer = 9702, 9703
    await character.create(seller, "seller")
    await character.create(buyer, "buyer")
    await character.add_item(seller, "星陨砂", 3)
    await character.add_stone(buyer, 1000)
    before_seller = (await character.get(seller)).spirit_stone

    listing = await market.create_listing(seller, "星陨砂", 2, 200, now=1000)
    res = await market.buy(buyer, listing["listing_id"], now=1001)

    assert res["status"] == "ok"
    assert res["tax"] == 10
    assert await character.item_qty(buyer, "星陨砂", bound=0) == 2
    assert await character.item_qty(seller, "星陨砂", bound=0) == 1
    assert (await character.get(seller)).spirit_stone == before_seller + 190
    assert (await character.get(buyer)).spirit_stone == 900
    assert (await market.buy(9704, listing["listing_id"], now=1002))["status"] == "not_available"


@pytest.mark.asyncio
async def test_market_cancel_returns_items(temp_db):
    uid = 9704
    await character.create(uid, "cancel")
    await character.add_item(uid, "幽都魂晶", 2)

    listing = await market.create_listing(uid, "幽都魂晶", 2, 300, now=1000)
    assert await character.item_qty(uid, "幽都魂晶") == 0
    res = await market.cancel(uid, listing["listing_id"], now=1001)

    assert res["status"] == "ok"
    assert await character.item_qty(uid, "幽都魂晶") == 2
    assert (await market.cancel(uid, listing["listing_id"], now=1002))["status"] == "not_available"


@pytest.mark.asyncio
async def test_market_self_buy_and_no_stone_are_blocked(temp_db):
    seller, buyer = 9705, 9706
    await character.create(seller, "seller")
    await character.create(buyer, "poor")
    await character.add_item(seller, "天外残玉", 1)

    listing = await market.create_listing(seller, "天外残玉", 1, 500, now=1000)

    assert (await market.buy(seller, listing["listing_id"], now=1001))["status"] == "self_buy"
    assert (await market.buy(buyer, listing["listing_id"], now=1001))["status"] == "no_stone"
    assert await character.item_qty(seller, "天外残玉") == 0


@pytest.mark.asyncio
async def test_market_audit_flags_high_price(temp_db):
    uid = 9707
    await character.create(uid, "audit")
    await character.add_item(uid, "星陨砂", 1)
    await market.create_listing(uid, "星陨砂", 1, 2_000_000, now=1000)

    rows = await market.audit_suspicious()

    assert rows and rows[0]["price"] == 2_000_000


@pytest.mark.asyncio
async def test_key_materials_cannot_be_listed_even_unbound(temp_db):
    """R-P0-1：转修令/化神丹/保命符即便以 bound=0 进包也不得上架（绑定隔离红线）。"""
    uid = 9708
    await character.create(uid, "exploit")
    for key in ("转修令", "化神丹", "保命符"):
        await character.add_item(uid, key, 2, bound=0)
        res = await market.create_listing(uid, key, 1, 100, now=1000)
        assert res["status"] == "no_trade", key
        # 未被扣库存，仍在背包。
        assert await character.item_qty(uid, key, bound=0) == 2, key


@pytest.mark.asyncio
async def test_ordinary_material_still_tradable(temp_db):
    uid = 9709
    await character.create(uid, "ok")
    await character.add_item(uid, "星陨砂", 1, bound=0)
    res = await market.create_listing(uid, "星陨砂", 1, 100, now=1000)
    assert res["status"] == "ok"


def test_market_tax_rate_positive():
    assert market.MARKET_TAX_RATE > 0


def test_list_price_clamp_floors_at_min_and_caps_max():
    from handlers.market import _clamp_price, MIN_LIST_PRICE, MAX_LIST_PRICE

    assert _clamp_price(0) == MIN_LIST_PRICE       # 不能低于下限（防 -100 到 0）
    assert _clamp_price(350) == 350
    assert _clamp_price(10 ** 12) == MAX_LIST_PRICE


@pytest.mark.asyncio
async def test_price_editor_reflects_adjusted_price(temp_db):
    from handlers.market import render_listing_editor

    uid = 9710
    await character.create(uid, "pricer")
    text, markup = await render_listing_editor(uid, "星陨砂", 300)

    assert "300 灵石" in text
    # 有 -100 / +100 / 确认 三类按钮。
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert any("100" in x for x in labels)
    assert any("确认上架" in x for x in labels)


@pytest.mark.asyncio
async def test_custom_price_listing_is_honored(temp_db):
    """定价编辑器最终走 create_listing——自定义单价按原样落库。"""
    uid = 9711
    await character.create(uid, "seller2")
    await character.add_item(uid, "星陨砂", 1)

    res = await market.create_listing(uid, "星陨砂", 1, 777, now=1000)

    assert res["status"] == "ok" and res["price"] == 777


@pytest.mark.asyncio
async def test_custom_quantity_listing_is_honored(temp_db):
    uid = 9715
    await character.create(uid, "seller-qty")
    await character.add_item(uid, "星陨砂", 4)

    res = await market.create_listing(uid, "星陨砂", 3, 900, now=1000)

    assert res["status"] == "ok"
    assert res["qty"] == 3
    assert await character.item_qty(uid, "星陨砂") == 1


@pytest.mark.asyncio
async def test_listing_rejects_illegal_quantity_and_price(temp_db):
    uid = 9716
    await character.create(uid, "bad-list")
    await character.add_item(uid, "星陨砂", 1)

    assert (await market.create_listing(uid, "星陨砂", 0, 100, now=1000))["status"] == "bad_request"
    assert (await market.create_listing(uid, "星陨砂", 1, 0, now=1000))["status"] == "bad_request"
    assert await character.item_qty(uid, "星陨砂") == 1


@pytest.mark.asyncio
async def test_listing_editor_reflects_adjusted_quantity(temp_db):
    from handlers.market import render_listing_editor

    uid = 9717
    await character.create(uid, "qty-editor")
    await character.add_item(uid, "星陨砂", 3)
    text, markup = await render_listing_editor(uid, "星陨砂", 500, qty=2)

    assert "星陨砂 ×2" in text
    assert "非绑定库存：3" in text
    assert "总价：500 灵石" in text
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert "➖ 1" in labels
    assert "➕ 1" in labels
    assert any("×2 / 500" in x for x in labels)


def test_market_listing_payload_parser_keeps_legacy_tokens_compatible():
    from handlers.market import DEFAULT_LIST_QTY, _parse_listing_payload

    assert _parse_listing_payload("price", "星陨砂:300") == ("星陨砂", DEFAULT_LIST_QTY, 300)
    assert _parse_listing_payload("confirm", "星陨砂:300") == ("星陨砂", DEFAULT_LIST_QTY, 300)
    assert _parse_listing_payload("price", "星陨砂:2:300") == ("星陨砂", 2, 300)
    assert _parse_listing_payload("qty", "星陨砂:300:2") == ("星陨砂", 2, 300)
    assert _parse_listing_payload("edit", "星陨砂:2:300") == ("星陨砂", 2, 300)
    assert _parse_listing_payload("edit", "星陨砂:bad:300") is None


def test_market_audit_db_arg_requires_existing_file(tmp_path, monkeypatch):
    from tools.market_audit import resolve_db_arg

    monkeypatch.chdir(tmp_path)
    db_file = tmp_path / "game.db"
    db_file.write_text("")

    assert resolve_db_arg("game.db") == str(db_file)
    with pytest.raises(SystemExit):
        resolve_db_arg("missing.db")


@pytest.mark.asyncio
async def test_market_audit_flags_frequent_trades(temp_db):
    seller, buyer = 9718, 9719
    await character.create(seller, "audit-seller")
    await character.create(buyer, "audit-buyer")
    await character.add_item(seller, "星陨砂", 3)
    await character.add_stone(buyer, 1000)
    for idx in range(3):
        listing = await market.create_listing(seller, "星陨砂", 1, 100 + idx, now=1000 + idx)
        assert (await market.buy(buyer, listing["listing_id"], now=1100 + idx))["status"] == "ok"

    rows = await market.audit_frequent_trades(now=2000, window_seconds=2000, min_trades=3)
    report = await market.audit_report(now=2000, window_seconds=2000, min_trades=3)

    assert rows
    assert rows[0]["seller_id"] == seller
    assert rows[0]["buyer_id"] == buyer
    assert rows[0]["trades"] == 3
    assert report["frequent_trades"]


@pytest.mark.asyncio
async def test_market_hourly_broadcast_sends_recent_listings_once(temp_db):
    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text):
            self.sent.append((chat_id, text))

    seller = 9712
    chat_id = -5801
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?)",
        (chat_id, "坊市群", 900))
    await character.create(seller, "seller-news")
    await character.add_item(seller, "星陨砂", 1)
    await market.create_listing(seller, "星陨砂", 1, 888, now=1000)

    bot = FakeBot()
    res = await market.notify_recent_listings(bot, now=4600)
    again = await market.notify_recent_listings(bot, now=8200)

    assert res == {"sent": 1, "failed": 0, "skipped": 0, "listings": 1}
    assert again == {"sent": 0, "failed": 0, "skipped": 1, "listings": 0}
    assert len(bot.sent) == 1
    sent_chat, text = bot.sent[0]
    assert sent_chat == chat_id
    assert "坊市上新" in text
    assert "星陨砂×1" in text
    assert "888灵石" in text
    assert "seller-news" in text
    assert "/market" in text


@pytest.mark.asyncio
async def test_market_hourly_broadcast_is_quiet_without_new_listings(temp_db):
    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text):
            self.sent.append((chat_id, text))

    seller = 9713
    chat_id = -5802
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?)",
        (chat_id, "清静群", 900))

    bot = FakeBot()
    quiet = await market.notify_recent_listings(bot, now=4600)

    await character.create(seller, "late-seller")
    await character.add_item(seller, "幽都魂晶", 1)
    await market.create_listing(seller, "幽都魂晶", 1, 666, now=4700)
    later = await market.notify_recent_listings(bot, now=8300)

    assert quiet == {"sent": 0, "failed": 0, "skipped": 1, "listings": 0}
    assert later == {"sent": 1, "failed": 0, "skipped": 0, "listings": 1}
    assert len(bot.sent) == 1
    assert "幽都魂晶×1" in bot.sent[0][1]


@pytest.mark.asyncio
async def test_market_broadcast_failure_logs_and_advances_window(temp_db, caplog):
    class FailingBot:
        async def send_message(self, chat_id, text):
            raise RuntimeError("bot kicked")

    seller = 9714
    chat_id = -5803
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?)",
        (chat_id, "失联群", 900))
    await character.create(seller, "blocked-seller")
    await character.add_item(seller, "星陨砂", 1)
    await market.create_listing(seller, "星陨砂", 1, 999, now=1000)

    with caplog.at_level(logging.WARNING, logger="xian.market"):
        failed = await market.notify_recent_listings(FailingBot(), now=4600)
    later = await market.notify_recent_listings(FailingBot(), now=8200)
    state = await db.fetchone(
        "SELECT last_notified_at FROM market_broadcast_state WHERE chat_id=?",
        (chat_id,))

    assert failed == {"sent": 0, "failed": 1, "skipped": 0, "listings": 0}
    assert later == {"sent": 0, "failed": 0, "skipped": 1, "listings": 0}
    assert state["last_notified_at"] == 8200
    assert "market broadcast send failed" in caplog.text
    assert "bot kicked" in caplog.text
