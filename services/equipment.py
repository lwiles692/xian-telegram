from __future__ import annotations

"""法宝长线 sink：强化 / 重铸 / 分解（#13）。

可重复消耗灵石 + 器魂；强化成本随级递增（收益递减）；多余法宝分解为器魂，
反哺强化/重铸，形成闭环。重铸复用炼器的词条 roll 逻辑。
"""

import json

from config.equipment import (ENHANCE_MAX_LEVEL, QIHUN_KEY, decompose_yield,
                              enhance_cost, reforge_cost)
from config.items import equipment_slot, item_name
from models import db
from services import character
from services.crafting import _roll_affixes


async def _get_instance(conn, user_id: int, instance_id: int):
    return await character.item_instance_for_action_conn(conn, user_id, instance_id)


async def _char_row(conn, user_id: int):
    cur = await conn.execute(
        "SELECT root_bone, forge_prof, spirit_stone FROM characters WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _item_qty(conn, user_id: int, key: str) -> int:
    return await character.item_qty_conn(conn, user_id, key)


async def _add_item(conn, user_id: int, key: str, qty: int, bound: int = 0):
    await conn.execute(
        "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = qty + ?",
        (user_id, key, int(bool(bound)), qty, qty))


async def _charge(conn, user_id: int, cost: dict) -> dict:
    """扣除灵石 + 材料；不足则返回失败且不扣减。"""
    char = await _char_row(conn, user_id)
    if not char:
        return {"status": "missing"}
    stone_cost = cost.get("stone", 0)
    if char["spirit_stone"] < stone_cost:
        return {"status": "no_stone", "need": stone_cost, "have": char["spirit_stone"]}
    mats = {k: v for k, v in cost.items() if k != "stone"}
    for key, qty in mats.items():
        have = await _item_qty(conn, user_id, key)
        if have < qty:
            return {"status": "no_material", "item": item_name(key), "need": qty, "have": have}
    if stone_cost:
        await conn.execute(
            "UPDATE characters SET spirit_stone = spirit_stone - ? WHERE user_id=?",
            (stone_cost, user_id))
    for key, qty in mats.items():
        await character.consume_item_conn(conn, user_id, key, qty)
    return {"status": "ok"}


async def enhance(user_id: int, instance_id: int) -> dict:
    async with db.transaction() as conn:
        lookup = await _get_instance(conn, user_id, instance_id)
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        if not equipment_slot(inst["base_key"]):
            return {"status": "not_equipment"}
        level = inst["enhance_level"]
        if level >= ENHANCE_MAX_LEVEL:
            return {"status": "max", "level": level}
        cost = enhance_cost(level)
        pay = await _charge(conn, user_id, cost)
        if pay["status"] != "ok":
            return pay
        await conn.execute(
            "UPDATE item_instances SET enhance_level=? WHERE id=? AND user_id=?",
            (level + 1, instance_id, user_id))
        return {"status": "ok", "name": item_name(inst["base_key"]),
                "level": level + 1, "cost": cost}


async def reforge(user_id: int, instance_id: int) -> dict:
    async with db.transaction() as conn:
        lookup = await _get_instance(conn, user_id, instance_id)
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        if not equipment_slot(inst["base_key"]):
            return {"status": "not_equipment"}
        cost = reforge_cost(inst["tier"])
        pay = await _charge(conn, user_id, cost)
        if pay["status"] != "ok":
            return pay
        char = await _char_row(conn, user_id)
        affixes = _roll_affixes(inst["base_key"], char["root_bone"], char["forge_prof"])
        await conn.execute(
            "UPDATE item_instances SET affixes_json=? WHERE id=? AND user_id=?",
            (json.dumps(affixes, ensure_ascii=False), instance_id, user_id))
        return {"status": "ok", "name": item_name(inst["base_key"]),
                "affixes": affixes, "cost": cost}


async def unequip(user_id: int, instance_id: int) -> dict:
    async with db.transaction() as conn:
        lookup = await _get_instance(conn, user_id, instance_id)
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        if not equipment_slot(inst["base_key"]):
            return {"status": "not_equipment"}
        if not inst["equipped_slot"]:
            return {"status": "not_equipped"}
        await conn.execute(
            "UPDATE item_instances SET equipped_slot=NULL WHERE id=? AND user_id=?",
            (instance_id, user_id))
        return {"status": "ok", "name": item_name(inst["base_key"]), "unequipped": True}


async def decompose(user_id: int, instance_id: int) -> dict:
    async with db.transaction() as conn:
        lookup = await _get_instance(conn, user_id, instance_id)
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        if inst["equipped_slot"]:
            return {"status": "equipped"}
        qihun = decompose_yield(inst["tier"], inst["enhance_level"])
        await conn.execute(
            "DELETE FROM item_instances WHERE id=? AND user_id=?", (instance_id, user_id))
        await _add_item(conn, user_id, QIHUN_KEY, qihun)
        return {"status": "ok", "name": item_name(inst["base_key"]), "qihun": qihun}
