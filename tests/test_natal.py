from __future__ import annotations

import json

import pytest
import pytest_asyncio

from config import natal as NATAL
from config import realms as R
from config.items import ITEMS
from models import db
from services import auction, character, equipment, natal


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "natal.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _备好角色(user_id: int, realm: int = 3):
    await character.create(user_id, f"本命道友{user_id}")
    await character.set_progress(user_id, realm, 0, 0)


async def _实例(user_id: int, key: str = "天魔刃") -> int:
    await character.create_item_instance(user_id, key)
    row = await db.fetchone(
        "SELECT id FROM item_instances WHERE user_id=? AND base_key=? ORDER BY id DESC LIMIT 1",
        (user_id, key))
    return int(row["id"])


async def _给材料(user_id: int, cost: dict):
    await character.add_stone(user_id, int(cost.get("stone", 0)))
    for key, qty in cost.get("items", {}).items():
        await character.add_item(user_id, key, int(qty))


async def _记住群(user_id: int, chat_id: int, now: int):
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=?, last_seen_at=?",
        (chat_id, "本命群", now, "本命群", now))
    await db.execute(
        "INSERT INTO bot_chat_members(chat_id, user_id, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen_at=?",
        (chat_id, user_id, now, now))


@pytest.mark.asyncio
async def test_schema_本命字段幂等回填(temp_db):
    char_cols = await db.fetchall("PRAGMA table_info(characters)")
    inst_cols = await db.fetchall("PRAGMA table_info(item_instances)")
    logs = await db.fetchall("PRAGMA table_info(natal_feed_logs)")

    assert "natal_instance_id" in {row["name"] for row in char_cols}
    assert {"natal_level", "bound"} <= {row["name"] for row in inst_cols}
    assert {"user_id", "instance_id", "level", "cost_json", "fed_at"} <= {
        row["name"] for row in logs}


@pytest.mark.asyncio
async def test_认主扣费绑定实例并写角色指针与播报(temp_db):
    uid = 9101
    now = 10_000
    await _备好角色(uid, realm=3)
    inst_id = await _实例(uid, "天魔刃")
    await _给材料(uid, NATAL.bind_cost("宝"))
    await _记住群(uid, -9101, now)

    res = await natal.bind(uid, inst_id, now=now)
    char = await character.get(uid)
    inst = await db.fetchone(
        "SELECT bound, natal_level FROM item_instances WHERE id=?",
        (inst_id,))
    events = await db.fetchall(
        "SELECT event_type, text FROM social_broadcasts WHERE user_id=?",
        (uid,))

    assert res["status"] == "ok"
    assert res["level"] == 1
    assert char.natal_instance_id == inst_id
    assert dict(inst) == {"bound": 1, "natal_level": 1}
    assert await character.item_qty(uid, "器魂") == 0
    assert await character.item_qty(uid, "天材地宝") == 0
    assert any(row["event_type"] == "natal.bind" and "本命法宝" in row["text"]
               for row in events)


@pytest.mark.asyncio
async def test_认主准入拦境界品阶拍卖与已有本命(temp_db):
    low_id = 9111
    await _备好角色(low_id, realm=2)
    low_inst = await _实例(low_id, "天魔刃")
    assert (await natal.bind(low_id, low_inst))["status"] == "realm_low"

    uid = 9112
    await _备好角色(uid, realm=3)
    ling_inst = await _实例(uid, "玄铁剑")
    assert (await natal.bind(uid, ling_inst))["status"] == "tier_low"

    auction_inst = await _实例(uid, "天魔刃")
    await db.execute(
        "UPDATE item_instances SET status='auction' WHERE id=?",
        (auction_inst,))
    assert (await natal.bind(uid, auction_inst))["status"] == "locked"

    bind_inst = await _实例(uid, "天魔刃")
    await _给材料(uid, NATAL.bind_cost("宝"))
    assert (await natal.bind(uid, bind_inst))["status"] == "ok"
    other_inst = await _实例(uid, "古战佩")
    assert (await natal.bind(uid, other_inst))["status"] == "already_has_natal"


@pytest.mark.asyncio
async def test_喂养按等级扣费且器修降低灵石与器魂(temp_db):
    uid = 9121
    await _备好角色(uid, realm=3)
    inst_id = await _实例(uid, "天魔刃")
    await _给材料(uid, NATAL.bind_cost("宝"))
    assert (await natal.bind(uid, inst_id, now=20_000))["status"] == "ok"
    await db.execute(
        "INSERT INTO dao_paths(user_id, path_key, xp, rank, active, unlocked_at) "
        "VALUES(?,?,?,?,?,?)",
        (uid, NATAL.FORGE_PATH_KEY, 0, 0, 1, 20_000))
    cost = NATAL.feed_cost(2, forge_path=True)
    await _给材料(uid, cost)

    res = await natal.feed(uid, now=20_100)
    inst = await db.fetchone(
        "SELECT natal_level FROM item_instances WHERE id=?",
        (inst_id,))
    log = await db.fetchone(
        "SELECT cost_json FROM natal_feed_logs WHERE user_id=? AND instance_id=? AND level=2",
        (uid, inst_id))

    assert res["status"] == "ok"
    assert res["forge_discount"] is True
    assert res["cost"] == {"stone": 3600, "items": {"器魂": 2, "星陨砂": 1}}
    assert inst["natal_level"] == 2
    assert json.loads(log["cost_json"]) == res["cost"]
    assert await character.item_qty(uid, "器魂") == 0
    assert await character.item_qty(uid, "星陨砂") == 0


@pytest.mark.asyncio
async def test_本命百分比进入战斗属性_clamp_不旁路(temp_db):
    uid = 9131
    await _备好角色(uid, realm=3)
    inst_id = await _实例(uid, "天魔刃")
    await character.equip_instance(uid, inst_id)
    until = 9_999_999_999
    await db.execute(
        "UPDATE characters SET debuff_json=? WHERE user_id=?",
        (json.dumps({"buffs": {"test": {"until": until, "effects": {"atk_pct": 0.23}}}},
                    ensure_ascii=False), uid))
    await db.execute(
        "UPDATE item_instances SET natal_level=10, bound=1 WHERE id=?",
        (inst_id,))

    stats = await character.stats(await character.get(uid))
    flat_atk = R.base_stats(3, 0)["atk"] + ITEMS["天魔刃"]["bonus"]["atk"]

    assert stats["atk"] == int(flat_atk * 1.25)


@pytest.mark.asyncio
async def test_本命实例不可上拍不可分解_斩缚后仍绑定(temp_db):
    uid = 9141
    await _备好角色(uid, realm=3)
    inst_id = await _实例(uid, "天魔刃")
    await _给材料(uid, NATAL.bind_cost("宝"))
    assert (await natal.bind(uid, inst_id, now=30_000))["status"] == "ok"

    listed = await auction.create_equipment_auction(uid, inst_id, 1_000, now=30_010)
    decomposed = await equipment.decompose(uid, inst_id)
    await character.add_stone(uid, NATAL.unbind_cost(1))
    unbound = await natal.unbind(uid, now=30_020)
    listed_after = await auction.create_equipment_auction(uid, inst_id, 1_000, now=30_030)
    decomposed_after = await equipment.decompose(uid, inst_id)
    rebound = await natal.bind(uid, inst_id, now=30_040)
    inst = await db.fetchone(
        "SELECT bound, natal_level FROM item_instances WHERE id=?",
        (inst_id,))

    assert listed["status"] == "bound"
    assert decomposed["status"] == "natal_bound"
    assert unbound["status"] == "ok"
    assert dict(inst) == {"bound": 1, "natal_level": 0}
    assert listed_after["status"] == "bound"
    assert decomposed_after["status"] == "natal_bound"
    assert rebound["status"] == "natal_bound"
    assert (await character.get(uid)).natal_instance_id is None


@pytest.mark.asyncio
async def test_坏档仅角色指针指向本命也不可上拍分解(temp_db):
    uid = 9151
    await _备好角色(uid, realm=3)
    inst_id = await _实例(uid, "天魔刃")
    await db.execute(
        "UPDATE characters SET natal_instance_id=? WHERE user_id=?",
        (inst_id, uid))

    listed = await auction.create_equipment_auction(uid, inst_id, 1_000, now=40_000)
    decomposed = await equipment.decompose(uid, inst_id)

    assert listed["status"] == "bound"
    assert decomposed["status"] == "natal_bound"
