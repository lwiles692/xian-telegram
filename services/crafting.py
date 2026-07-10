"""炼丹 / 炼器：定时制造、惰性收取、灵石加速（spec §8）。"""
from __future__ import annotations

import json
import random
import time

from config import daohang as DAOHANG
from config.items import ITEMS, item_name
from config.recipes import ACCELERATE_STONE_PER_MINUTE, RECIPES
from models import db
from services import activity, character, dao_path, game_events


def _roll_affixes(base_key: str, root_bone: int, prof: int, rng=None,
                  quality_mult: float = 1.0) -> dict:
    rng = rng or random.Random()
    pool = [
        "atk_pct", "hp_pct", "df_pct", "lifesteal_pct", "reflect_pct",
        "initiative", "crit", "crit_resist", "pierce",
    ]
    rolls = 1 + int(root_bone >= 70) + int(prof >= 5)
    quality_mult = max(1.0, float(quality_mult))   # 器修 forge_pct 放大词条品质
    affixes = {}
    for key in rng.sample(pool, min(rolls, len(pool))):
        if key.endswith("_pct"):
            affixes[key] = round((rng.randint(3, 8) + prof * 0.5) / 100 * quality_mult, 3)
        else:
            affixes[key] = int(round((rng.randint(4, 12) + prof) * quality_mult))
    return affixes


def accelerate_cost(remaining_seconds: int) -> int:
    """按剩余分钟计加速费；已完成的任务免费收取。"""
    remaining = max(0, int(remaining_seconds))
    if remaining <= 0:
        return 0
    return ((remaining + 59) // 60) * ACCELERATE_STONE_PER_MINUTE


async def active_job(user_id: int):
    return await db.fetchone(
        "SELECT * FROM crafting_jobs WHERE user_id=? AND status='active' ORDER BY id LIMIT 1",
        (user_id,))


async def known_recipe_keys(user_id: int) -> set:
    rows = await db.fetchall("SELECT recipe_key FROM recipes_known WHERE user_id=?", (user_id,))
    return {row["recipe_key"] for row in rows}


async def available_recipes(user_id: int):
    char = await character.get(user_id)
    if not char:
        return []
    known = await known_recipe_keys(user_id)
    return [
        (key, recipe)
        for key, recipe in RECIPES.items()
        if char.realm >= recipe["realm"] and (recipe.get("default", False) or key in known)
    ]


async def collect_ready(user_id: int, now: int = None) -> list:
    now = int(time.time()) if now is None else now
    collected = []
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT * FROM crafting_jobs WHERE user_id=? AND status='active' AND finish_at<=? "
            "ORDER BY finish_at",
            (user_id, now))
        jobs = await cur.fetchall()
        await cur.close()
        if not jobs:
            return collected
        cur = await conn.execute("SELECT * FROM characters WHERE user_id=?", (user_id,))
        char = await cur.fetchone()
        await cur.close()
        dao_bonus = await dao_path.active_bonuses(user_id)
        forge_quality = 1.0 + float(dao_bonus.get("forge_pct", 0.0))
        for job in jobs:
            recipe = RECIPES[job["recipe_key"]]
            output = recipe["output"]
            entry = {}
            if output["kind"] == "equipment":
                base_key = output["key"]
                item = ITEMS[base_key]
                prof = char["forge_prof"] if recipe["type"] == "forge" else char["alchemy_prof"]
                quality = forge_quality if recipe["type"] == "forge" else 1.0
                affixes = _roll_affixes(base_key, char["root_bone"], prof, quality_mult=quality)
                await conn.execute(
                    "INSERT INTO item_instances(user_id, base_key, tier, affixes_json) "
                    "VALUES(?,?,?,?)",
                    (user_id, base_key, item.get("tier", "凡"),
                     json.dumps(affixes, ensure_ascii=False)))
                entry = {"kind": "equipment", "name": item_name(base_key)}
            else:
                bound = int(bool(output.get("bound", 0)))
                await conn.execute(
                    "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,?,?) "
                    "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = qty + ?",
                    (user_id, output["key"], bound, output["qty"], output["qty"]))
                entry = {"kind": "item", "name": item_name(output["key"]), "qty": output["qty"]}
                if bound:
                    entry["bound"] = bound
            column = "alchemy_prof" if recipe["type"] == "alchemy" else "forge_prof"
            await conn.execute(
                f"UPDATE characters SET {column} = {column} + 1 WHERE user_id=?",
                (user_id,))
            daohang = await character.grant_regular_daohang_conn(
                conn, user_id, DAOHANG.CRAFT_DAOHANG_BY_TYPE.get(recipe["type"], 0),
                "craft_regular", now, realm=char["realm"])
            if daohang:
                entry["daohang"] = daohang
            collected.append(entry)
            await conn.execute("UPDATE crafting_jobs SET status='done' WHERE id=?", (job["id"],))
            await game_events.emit_conn(
                conn, user_id, "craft.done",
                {"recipe_key": job["recipe_key"], "craft_type": recipe["type"], "amount": 1},
                now)
    return collected


async def start_job(user_id: int, recipe_key: str, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    recipe = RECIPES.get(recipe_key)
    if not recipe:
        return {"status": "bad_recipe"}
    await collect_ready(user_id, now)
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM characters WHERE user_id=?", (user_id,))
        char = await cur.fetchone()
        await cur.close()
        if not char:
            return {"status": "missing"}
        if char["realm"] < recipe["realm"]:
            return {"status": "locked"}
        if not recipe.get("default", False):
            cur = await conn.execute(
                "SELECT 1 FROM recipes_known WHERE user_id=? AND recipe_key=?",
                (user_id, recipe_key))
            known = await cur.fetchone()
            await cur.close()
            if not known:
                return {"status": "need_recipe"}
        cur = await conn.execute(
            "SELECT 1 FROM crafting_jobs WHERE user_id=? AND status='active'", (user_id,))
        busy = await cur.fetchone()
        await cur.close()
        if busy:
            return {"status": "busy"}
        if char["spirit_stone"] < recipe["stone"]:
            return {"status": "no_stone", "need": recipe["stone"], "have": char["spirit_stone"]}
        missing = []
        for key, qty in recipe["materials"].items():
            have = await character.item_qty_conn(conn, user_id, key)
            if have < qty:
                missing.append({"item": key, "need": qty, "have": have})
        if missing:
            return {"status": "no_material", "missing": missing}
        await conn.execute(
            "UPDATE characters SET spirit_stone = spirit_stone - ? WHERE user_id=?",
            (recipe["stone"], user_id))
        for key, qty in recipe["materials"].items():
            await character.consume_item_conn(conn, user_id, key, qty)
        finish_at = now + recipe["seconds"]
        await conn.execute(
            "INSERT INTO crafting_jobs(user_id, craft_type, recipe_key, start_at, finish_at, status) "
            "VALUES(?,?,?,?,?,'active')",
            (user_id, recipe["type"], recipe_key, now, finish_at))
        await activity.record_window(user_id, "craft", recipe_key, now, finish_at, conn=conn)
        return {"status": "started", "name": recipe["name"], "finish_at": finish_at,
                "seconds": recipe["seconds"]}


async def accelerate(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT * FROM crafting_jobs WHERE user_id=? AND status='active' ORDER BY id LIMIT 1",
            (user_id,))
        job = await cur.fetchone()
        await cur.close()
        if not job:
            return {"status": "no_job"}
        remaining = job["finish_at"] - now
        cost = accelerate_cost(remaining)
        if cost > 0:
            cur = await conn.execute("SELECT spirit_stone FROM characters WHERE user_id=?", (user_id,))
            char = await cur.fetchone()
            await cur.close()
            if char["spirit_stone"] < cost:
                return {"status": "no_stone", "need": cost, "have": char["spirit_stone"]}
            await conn.execute(
                "UPDATE characters SET spirit_stone = spirit_stone - ? WHERE user_id=?",
                (cost, user_id))
            await conn.execute("UPDATE crafting_jobs SET finish_at=? WHERE id=?", (now, job["id"]))
            await conn.execute(
                "UPDATE activity_windows SET finish_at=? "
                "WHERE user_id=? AND kind='craft' AND source_key=? "
                "AND start_at=? AND finish_at=?",
                (now, user_id, job["recipe_key"], job["start_at"], job["finish_at"]))
    return {"status": "accelerated", "cost": cost, "collected": await collect_ready(user_id, now)}
