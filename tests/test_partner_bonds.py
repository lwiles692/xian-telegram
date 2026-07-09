from __future__ import annotations

import pytest
import pytest_asyncio

from models import db
from services import character


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "partner-bonds.db"))
    yield
    await db.close_db()


async def _备好境界(user_id: int, name: str, realm: int):
    await character.create(user_id, name)
    await character.set_progress(user_id, realm, 0, 0)


async def _记住群(user_id: int, chat_id: int, now: int):
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=?, last_seen_at=?",
        (chat_id, "问道群", now, "问道群", now))
    await db.execute(
        "INSERT INTO bot_chat_members(chat_id, user_id, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen_at=?",
        (chat_id, user_id, now, now))


async def _道侣行(a_id: int, b_id: int):
    return await db.fetchone(
        "SELECT * FROM social_bonds WHERE kind='partner' AND a_id=? AND b_id=?",
        (a_id, b_id))


async def _道侣双行(a_id: int, b_id: int):
    return await db.fetchall(
        "SELECT * FROM social_bonds WHERE kind='partner' "
        "AND ((a_id=? AND b_id=?) OR (a_id=? AND b_id=?)) ORDER BY a_id",
        (a_id, b_id, b_id, a_id))


async def _激活道侣(a_id: int, b_id: int, now: int) -> dict:
    from config import bonds as BONDS
    from services import bonds

    await _备好境界(a_id, f"结缘道友{a_id}", 2)
    await _备好境界(b_id, f"结缘道友{b_id}", 2)
    await character.add_item(a_id, BONDS.PARTNER_TOKEN_ITEM, 1, bound=1)
    pending = await bonds.create_pending_partner_request(a_id, b_id, initiator_id=a_id, now=now)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=b_id, now=now + 1)
    assert confirmed["status"] == "ok"
    return confirmed


@pytest.mark.asyncio
async def test_同心结来自活动商店且互赠白名单不含破境核心丹(temp_db):
    from config import bonds as BONDS
    from config import items as ITEMS
    from config import weekly_events as WEEKLY
    from services import weekly_events

    uid = 5101
    await _备好境界(uid, "结缘道友5101", 2)
    await character.add_item(uid, WEEKLY.ACTIVITY_MATERIAL, 6, bound=1)

    res = await weekly_events.exchange(uid, "heart_knot", now=1000)

    assert res == {
        "status": "ok",
        "kind": "item",
        "name": "同心结",
        "item": BONDS.PARTNER_TOKEN_ITEM,
        "qty": 1,
        "cost": 6,
    }
    assert ITEMS.ITEMS[BONDS.PARTNER_TOKEN_ITEM]["name"] == "同心结"
    assert BONDS.PARTNER_TOKEN_ITEM in ITEMS.NO_TRADE
    assert WEEKLY.SHOP_OFFERS["heart_knot"]["reward_item"] == BONDS.PARTNER_TOKEN_ITEM
    assert await character.item_qty(uid, BONDS.PARTNER_TOKEN_ITEM, bound=1) == 1
    assert BONDS.is_partner_gift_allowed("疗伤丹") is True
    assert BONDS.is_partner_gift_allowed("化神丹") is False
    assert BONDS.is_partner_gift_allowed("炼虚丹") is False


@pytest.mark.asyncio
async def test_结契待确认写镜像双行且确认需另一方与同心结(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 20_000
    await _备好境界(5201, "金丹道友5201", 2)
    await _备好境界(5202, "金丹道友5202", 2)
    pending = await bonds.create_pending_partner_request(
        5201, 5202, initiator_id=5201, now=now)
    assert pending["status"] == "ok"

    rows = await _道侣双行(5201, 5202)
    assert {(row["a_id"], row["b_id"]) for row in rows} == {(5201, 5202), (5202, 5201)}
    assert {row["status"] for row in rows} == {BONDS.STATUS_PENDING}
    assert {row["initiator_id"] for row in rows} == {5201}
    assert {row["expires_at"] for row in rows} == {now + BONDS.PENDING_EXPIRE_SECONDS}

    self_confirm = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=5201, now=now + 10)
    stranger = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=9999, now=now + 20)
    no_token = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=5202, now=now + 30)

    assert self_confirm["status"] == "need_counterparty"
    assert stranger["status"] == "forbidden"
    assert no_token == {"status": "no_token", "item": BONDS.PARTNER_TOKEN_ITEM}
    assert {row["status"] for row in await _道侣双行(5201, 5202)} == {BONDS.STATUS_PENDING}


@pytest.mark.asyncio
async def test_结契确认消耗绑定同心结并播报_一人一侣由服务拦截(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 30_000
    await _备好境界(5301, "青鸾5301", 2)
    await _备好境界(5302, "玄鹤5302", 2)
    await _备好境界(5303, "旁观道友5303", 2)
    await _记住群(5301, -30001, now)
    await character.add_item(5301, BONDS.PARTNER_TOKEN_ITEM, 1, bound=1)
    pending = await bonds.create_pending_partner_request(
        5301, 5302, initiator_id=5301, now=now)

    confirmed = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=5302, now=now + 10)

    assert confirmed["status"] == "ok"
    assert confirmed["token_owner"] == 5301
    assert await character.item_qty(5301, BONDS.PARTNER_TOKEN_ITEM, bound=1) == 0
    rows = await _道侣双行(5301, 5302)
    assert {row["status"] for row in rows} == {BONDS.STATUS_ACTIVE}
    assert {row["activated_at"] for row in rows} == {now + 10}
    assert {row["confirmed_at"] for row in rows} == {now + 10}

    blocked = await bonds.create_pending_partner_request(
        5301, 5303, initiator_id=5301, now=now + 20)
    assert blocked["status"] == "already_has_partner"

    broadcasts = await db.fetchall(
        "SELECT event_type, text FROM social_broadcasts WHERE user_id=? ORDER BY id",
        (5301,))
    assert any(row["event_type"] == "partner.active" and "结为道侣" in row["text"]
               for row in broadcasts)


@pytest.mark.asyncio
async def test_拒绝结契不落冷却_解除扣灵石并同步镜像双行(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 40_000
    await _备好境界(5401, "孤鸿5401", 2)
    await _备好境界(5402, "照影5402", 2)
    declined = await bonds.create_pending_partner_request(
        5401, 5402, initiator_id=5401, now=now)
    assert declined["status"] == "ok"
    res = await bonds.decline_pending_partner_request(
        declined["bond_id"], user_id=5402, now=now + 10)
    assert res["status"] == "ok"
    assert res["changed"] == 2
    assert {row["status"] for row in await _道侣双行(5401, 5402)} == {BONDS.STATUS_DECLINED}
    assert (await bonds.can_start_partner_request(5401, 5402, now=now + 20))["status"] == "ok"

    await _备好境界(5403, "并蒂5403", 2)
    await _备好境界(5404, "连枝5404", 2)
    await character.add_item(5403, BONDS.PARTNER_TOKEN_ITEM, 1, bound=1)
    active = await bonds.create_pending_partner_request(
        5403, 5404, initiator_id=5403, now=now + 100)
    confirmed = await bonds.confirm_pending_partner_request(
        active["bond_id"], confirmer_id=5404, now=now + 110)
    assert confirmed["status"] == "ok"

    no_stone = await bonds.dissolve_active_bond(
        confirmed["mirror_bond_id"], user_id=5404, now=now + 120)
    assert no_stone["status"] == "no_stone"
    assert {row["status"] for row in await _道侣双行(5403, 5404)} == {BONDS.STATUS_ACTIVE}

    before_stone = (await character.get(5404)).spirit_stone
    await character.add_stone(5404, BONDS.PARTNER_DISSOLVE_STONE_COST)
    dissolved = await bonds.dissolve_active_bond(
        confirmed["mirror_bond_id"], user_id=5404, now=now + 130)
    after = await character.get(5404)

    assert dissolved["status"] == "ok"
    assert dissolved["cost"] == BONDS.PARTNER_DISSOLVE_STONE_COST
    assert after.spirit_stone == before_stone
    rows = await _道侣双行(5403, 5404)
    assert {row["status"] for row in rows} == {BONDS.STATUS_DISSOLVED}
    assert {row["dissolved_at"] for row in rows} == {now + 130}

    blocked = await bonds.can_start_partner_request(5403, 5404, now=now + 140)
    reopened = await bonds.can_start_partner_request(
        5403, 5404, now=dissolved["cooldown_until"])
    assert blocked["status"] == "cooldown"
    assert blocked["cooldown_until"] == dissolved["cooldown_until"]
    assert reopened["status"] == "ok"


@pytest.mark.asyncio
async def test_结契境界门槛_双方皆需金丹(temp_db):
    from config import bonds as BONDS
    from services import bonds

    await _备好境界(5501, "筑基道友5501", 1)
    await _备好境界(5502, "金丹道友5502", 2)

    res = await bonds.create_pending_partner_request(
        5501, 5502, initiator_id=5501, now=50_000)

    assert res["status"] == "realm_low"
    assert res["user_id"] == 5501
    assert res["need_realm"] == BONDS.PARTNER_MIN_REALM


@pytest.mark.asyncio
async def test_道侣每日互赠_只收绑定白名单且赠后仍绑定(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 60_000
    await _激活道侣(5601, 5602, now)
    await character.add_item(5601, "疗伤丹", 1, bound=0)

    unbound_only = await bonds.grant_daily_partner_gift(5601, "疗伤丹", now=now + 10)
    bad_item = await bonds.grant_daily_partner_gift(5601, "化神丹", now=now + 20)
    await character.add_item(5601, "疗伤丹", 2, bound=1)
    first = await bonds.grant_daily_partner_gift(5601, "疗伤丹", now=now + 30)

    assert unbound_only == {"status": "no_item", "item": "疗伤丹",
                            "need": BONDS.PARTNER_DAILY_GIFT_QTY, "have": 0}
    assert bad_item == {"status": "bad_item", "item": "化神丹"}
    assert first["status"] == "ok"
    assert first["receiver_id"] == 5602
    assert first["item"] == "疗伤丹"
    assert first["bound"] == 1
    assert await character.item_qty(5601, "疗伤丹", bound=0) == 1
    assert await character.item_qty(5601, "疗伤丹", bound=1) == 1
    assert await character.item_qty(5602, "疗伤丹", bound=1) == 1
    assert await character.item_qty(5602, "疗伤丹", bound=0) == 0
    row = await db.fetchone(
        "SELECT giver_id, receiver_id, item_key, qty FROM bond_daily_gifts "
        "WHERE giver_id=?",
        (5601,))
    assert dict(row) == {
        "giver_id": 5601,
        "receiver_id": 5602,
        "item_key": "疗伤丹",
        "qty": BONDS.PARTNER_DAILY_GIFT_QTY,
    }


@pytest.mark.asyncio
async def test_道侣每日互赠_同日幂等次日可再赠且非道侣不可赠(temp_db):
    from services import bonds

    now = 70_000
    await _激活道侣(5701, 5702, now)
    await _备好境界(5703, "无缘道友5703", 2)
    await character.add_item(5701, "补灵丹", 3, bound=1)
    await character.add_item(5703, "补灵丹", 1, bound=1)

    first = await bonds.grant_daily_partner_gift(5701, "补灵丹", now=now + 10)
    duplicate = await bonds.grant_daily_partner_gift(5701, "补灵丹", now=now + 20)
    next_day = await bonds.grant_daily_partner_gift(
        5701, "补灵丹", now=now + 24 * 3600 + 10)
    no_bond = await bonds.grant_daily_partner_gift(5703, "补灵丹", now=now + 30)

    assert first["status"] == "ok"
    assert duplicate["status"] == "daily_done"
    assert next_day["status"] == "ok"
    assert no_bond["status"] == "not_active"
    assert await character.item_qty(5701, "补灵丹", bound=1) == 1
    assert await character.item_qty(5702, "补灵丹", bound=1) == 2
    assert await character.item_qty(5703, "补灵丹", bound=1) == 1
