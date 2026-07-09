from __future__ import annotations

"""本命法宝服务（spec-v3 §7.2 / M5）。"""

import json
import time

from config import natal as CFG
from config.items import equipment_slot, item_name
from models import db
from services import character, game_events


def _now(now: int = None) -> int:
    return int(time.time()) if now is None else int(now)


async def bind(user_id: int, instance_id: int, now: int = None) -> dict:
    """认主：元婴期起，将宝/玄阶法宝实例绑定为本命法宝。"""
    now = _now(now)
    async with db.transaction() as conn:
        char = await _character_conn(conn, user_id)
        if not char:
            return {"status": "missing"}
        if int(char["realm"]) < CFG.MIN_REALM:
            return {"status": "realm_low", "need_realm": CFG.MIN_REALM}
        if char["natal_instance_id"]:
            return {"status": "already_has_natal", "instance_id": int(char["natal_instance_id"])}
        lookup = await character.item_instance_for_action_conn(conn, user_id, instance_id)
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        if not equipment_slot(inst["base_key"]):
            return {"status": "not_equipment"}
        if inst["tier"] not in CFG.ELIGIBLE_TIERS:
            return {"status": "tier_low", "tier": inst["tier"]}
        if int(inst["bound"] or 0) or int(inst["natal_level"] or 0):
            return {"status": "natal_bound"}
        cost = CFG.bind_cost(inst["tier"])
        paid = await _charge_conn(conn, user_id, cost)
        if paid["status"] != "ok":
            return paid
        await conn.execute(
            "UPDATE characters SET natal_instance_id=? WHERE user_id=?",
            (instance_id, user_id))
        await conn.execute(
            "UPDATE item_instances SET bound=1, natal_level=1 WHERE id=? AND user_id=?",
            (instance_id, user_id))
        await game_events.emit_conn(
            conn, user_id, "natal.bind",
            {"instance_id": instance_id, "item": item_name(inst["base_key"]),
             "level": 1, "amount": 1}, now)
    return {"status": "ok", "instance_id": int(instance_id), "level": 1,
            "item": item_name(inst["base_key"]), "cost": cost}


async def feed(user_id: int, instance_id: int | None = None, now: int = None) -> dict:
    """喂养当前本命法宝，提升一级；器修只降成本，不提高属性上限。"""
    now = _now(now)
    async with db.transaction() as conn:
        requested_id = instance_id
        char = await _character_conn(conn, user_id)
        if not char:
            return {"status": "missing"}
        instance_id = char["natal_instance_id"]
        if not instance_id:
            return {"status": "no_natal"}
        if requested_id is not None and int(requested_id) != int(char["natal_instance_id"]):
            return {"status": "not_active"}
        lookup = await character.item_instance_for_action_conn(conn, user_id, int(instance_id))
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        level = int(inst["natal_level"] or 0)
        if level <= 0:
            return {"status": "no_natal"}
        if level >= CFG.MAX_LEVEL:
            return {"status": "max", "level": level}
        target = level + 1
        forge_path = await _is_forge_path_conn(conn, user_id)
        cost = CFG.feed_cost(target, forge_path=forge_path)
        paid = await _charge_conn(conn, user_id, cost)
        if paid["status"] != "ok":
            return paid
        await conn.execute(
            "INSERT INTO natal_feed_logs(user_id, instance_id, level, cost_json, fed_at) "
            "VALUES(?,?,?,?,?)",
            (user_id, int(instance_id), target, json.dumps(cost, ensure_ascii=False), now))
        await conn.execute(
            "UPDATE item_instances SET natal_level=? WHERE id=? AND user_id=?",
            (target, int(instance_id), user_id))
    return {"status": "ok", "instance_id": int(instance_id), "level": target,
            "item": item_name(inst["base_key"]), "cost": cost, "forge_discount": forge_path}


async def unbind(user_id: int, instance_id: int | None = None, now: int = None) -> dict:
    """斩缚：高额灵石清空本命等级，保留绑定，给换本命留出口。"""
    now = _now(now)
    async with db.transaction() as conn:
        requested_id = instance_id
        char = await _character_conn(conn, user_id)
        if not char:
            return {"status": "missing"}
        instance_id = char["natal_instance_id"]
        if not instance_id:
            return {"status": "no_natal"}
        if requested_id is not None and int(requested_id) != int(char["natal_instance_id"]):
            return {"status": "not_active"}
        lookup = await character.item_instance_for_action_conn(conn, user_id, int(instance_id))
        if lookup["status"] != "ok":
            return {"status": lookup["status"]}
        inst = lookup["instance"]
        level = max(1, int(inst["natal_level"] or 1))
        cost = {"stone": CFG.unbind_cost(level), "items": {}}
        paid = await _charge_conn(conn, user_id, cost)
        if paid["status"] != "ok":
            return paid
        await conn.execute(
            "UPDATE characters SET natal_instance_id=NULL WHERE user_id=?",
            (user_id,))
        await conn.execute(
            "UPDATE item_instances SET natal_level=0, bound=1 WHERE id=? AND user_id=?",
            (int(instance_id), user_id))
        await game_events.emit_conn(
            conn, user_id, "natal.unbind",
            {"instance_id": int(instance_id), "item": item_name(inst["base_key"]),
             "level": level, "amount": 1}, now)
    return {"status": "ok", "instance_id": int(instance_id),
            "item": item_name(inst["base_key"]), "level": level, "cost": cost}


async def overview(user_id: int) -> dict:
    char = await character.get(user_id)
    if not char:
        return {"status": "missing"}
    rows = await character.item_instances(user_id)
    natal_id = getattr(char, "natal_instance_id", None)
    natal = next((row for row in rows if int(row["id"]) == int(natal_id or 0)), None)
    return {"status": "ok", "natal_instance_id": natal_id,
            "natal": natal, "instances": rows}


async def _character_conn(conn, user_id: int):
    cur = await conn.execute(
        "SELECT user_id, realm, spirit_stone, natal_instance_id FROM characters WHERE user_id=?",
        (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _is_forge_path_conn(conn, user_id: int) -> bool:
    cur = await conn.execute(
        "SELECT path_key FROM dao_paths WHERE user_id=? AND active=1 LIMIT 1",
        (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return bool(row and row["path_key"] == CFG.FORGE_PATH_KEY)


async def _charge_conn(conn, user_id: int, cost: dict) -> dict:
    stone = int(cost.get("stone", 0))
    if stone:
        char = await _character_conn(conn, user_id)
        if not char:
            return {"status": "missing"}
        if int(char["spirit_stone"]) < stone:
            return {"status": "no_stone", "need": stone, "have": int(char["spirit_stone"])}
    for key, qty in cost.get("items", {}).items():
        have = await character.item_qty_conn(conn, user_id, key)
        if have < int(qty):
            return {"status": "no_material", "item": item_name(key), "need": int(qty),
                    "have": have}
    if stone:
        await conn.execute(
            "UPDATE characters SET spirit_stone=spirit_stone-? WHERE user_id=?",
            (stone, user_id))
    for key, qty in cost.get("items", {}).items():
        await character.consume_item_conn(conn, user_id, key, int(qty))
    return {"status": "ok"}
