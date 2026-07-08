"""角色服务：注册/读取/属性计算/储物袋。读取时惰性恢复精力并落库。"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass

from config import daohang as DAOHANG
from config import realms as R
from config import buffs as BUFFS
from config.items import ITEMS, equipment_slot, item_name, weapon_bonus
from config.equipment import ENHANCE_PER_LEVEL
from config.sects import welfare as sect_welfare_config
from config.skills import (COMBAT_SLOTS, MIND_SLOT, SKILLS, STARTER_MIND, STARTER_SKILL,
                           is_mind_skill, skill_bonus)
from models import db
from services import activity, settle
from services import ascension, dao_path, sect_war

SPIRIT_ROOTS = ["天灵根", "金灵根", "木灵根", "水灵根", "火灵根",
                "土灵根", "雷灵根", "冰灵根", "风灵根", "五行杂灵根"]
ROOT_BONE_MIN = 40
ROOT_BONE_MAX = 80
AUTO_SECLUSION_IDLE_SECONDS = 3600


@dataclass
class Character:
    user_id: int
    root_bone: int
    spirit_root: str
    realm: int
    stage: int
    cultivation: int
    stamina: int
    stamina_at: int
    seclusion_at: int   # 0 表示未闭关
    spirit_stone: int
    weapon_key: str
    debuff_json: dict
    daohang: int
    current_hp: int = None   # None ⇒ 视为满（旧档/新建未 materialize）
    current_mp: int = None
    hp_at: int = None        # 气血回复惰性结算锚点；None ⇒ 视为 now
    mp_at: int = None


async def _select_character(conn, user_id: int):
    cur = await conn.execute("SELECT * FROM characters WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return row


async def _sect_welfare(conn, user_id: int) -> dict:
    cur = await conn.execute(
        "SELECT s.level FROM sect_members m JOIN sects s ON s.id=m.sect_id WHERE m.user_id=?",
        (user_id,))
    row = await cur.fetchone()
    await cur.close()
    return sect_welfare_config(row["level"]) if row else sect_welfare_config(0)


async def sect_welfare(user_id: int) -> dict:
    row = await db.fetchone(
        "SELECT s.level FROM sect_members m JOIN sects s ON s.id=m.sect_id WHERE m.user_id=?",
        (user_id,))
    return sect_welfare_config(row["level"]) if row else sect_welfare_config(0)


def _settled_stamina(row, now: int = None, welfare: dict = None):
    now = int(time.time()) if now is None else now
    welfare = welfare or sect_welfare_config(0)
    cap = R.STAMINA_CAP[row["realm"]] + welfare["stamina_bonus"]
    return settle.regen_stamina(row["stamina"], row["stamina_at"], cap, now)


def _from_row(row, stamina: int = None, stamina_at: int = None) -> Character:
    return Character(
        user_id=row["user_id"], root_bone=row["root_bone"], spirit_root=row["spirit_root"],
        realm=row["realm"], stage=row["stage"], cultivation=row["cultivation"],
        stamina=row["stamina"] if stamina is None else stamina,
        stamina_at=row["stamina_at"] if stamina_at is None else stamina_at,
        seclusion_at=row["seclusion_at"] or 0,
        spirit_stone=row["spirit_stone"], weapon_key=row["weapon_key"],
        debuff_json=json.loads(row["debuff_json"] or "{}"),
        daohang=row["daohang"] if "daohang" in row.keys() else 0,
        current_hp=row["current_hp"], current_mp=row["current_mp"],
        hp_at=row["hp_at"], mp_at=row["mp_at"])


COMBAT_MOD_KEYS = ("lifesteal_pct", "reflect_pct", "crit_resist", "pierce", "initiative")


def active_temporary_buffs(state: dict, now: int = None) -> list:
    now = int(time.time()) if now is None else now
    buffs = state.get("buffs") or {}
    active = []
    for buff in buffs.values():
        if int(buff.get("until", 0)) > now:
            active.append(buff)
    return active


def temporary_seclusion_pct(state: dict, now: int = None) -> float:
    return clamp_seclusion_pct(raw_temporary_seclusion_pct(state, now))


def raw_temporary_seclusion_pct(state: dict, now: int = None) -> float:
    pct = 0.0
    for buff in active_temporary_buffs(state, now):
        effects = buff.get("effects") or {}
        pct += float(effects.get("seclusion_pct", 0))
    return pct


def clamp_seclusion_pct(pct: float) -> float:
    return min(BUFFS.SECLUSION_PCT_CAP, max(0.0, float(pct)))


def _seclusion_remainder(state: dict, realm: int, stage: int) -> int:
    key = f"{realm}:{stage}"
    data = state.get("seclusion_remainder") or {}
    if data.get("key") != key:
        return 0
    return int(data.get("units", 0) or 0)


def _set_seclusion_remainder(state: dict, realm: int, stage: int, units: int):
    if units > 0:
        state["seclusion_remainder"] = {"key": f"{realm}:{stage}", "units": int(units)}
    else:
        state.pop("seclusion_remainder", None)


async def exists(user_id: int) -> bool:
    return await db.fetchone("SELECT 1 FROM characters WHERE user_id=?", (user_id,)) is not None


async def touch_user(user_id: int, username: str, now: int = None):
    now = int(time.time()) if now is None else now
    await db.execute(
        "UPDATE users SET username=?, last_seen_at=? WHERE tg_user_id=?",
        (username, now, user_id))


async def _has_active_job(conn, user_id: int) -> bool:
    """是否有进行中的定时任务（历练 / 秘境），用于让自动闭关避开它们。"""
    cur = await conn.execute(
        "SELECT 1 FROM explore_runs WHERE user_id=? AND status='active' "
        "UNION ALL "
        "SELECT 1 FROM dungeon_jobs WHERE user_id=? AND status='active' LIMIT 1",
        (user_id, user_id))
    row = await cur.fetchone()
    await cur.close()
    return row is not None


async def _add_daohang_event(conn, user_id: int, amount: int, event_type: str, now: int):
    if amount <= 0:
        return
    await conn.execute(
        "INSERT INTO path_events(user_id, path_key, event_type, amount, created_at) "
        "VALUES(?,NULL,?,?,?)",
        (user_id, event_type, amount, now))


def _overflow_week(now: int) -> str:
    return time.strftime("%Y-%W", time.localtime(now))


async def _cap_overflow_daohang(conn, user_id: int, raw: int, now: int) -> int:
    """溢出转道行受周上限约束，返回本次实际可入账的道行（已扣减本周已用额度）。

    满级/准满级挂机 100% 溢出，若不封顶会把道行做成绕过周经济的无限水管（元婴大圆满尤甚，
    该档飞升试炼未解锁、几乎无对口 sink）。计量落 weekly_activity.overflow_daohang。
    """
    if raw <= 0:
        return 0
    week = _overflow_week(now)
    cur = await conn.execute(
        "SELECT overflow_daohang FROM weekly_activity WHERE user_id=? AND week=?",
        (user_id, week))
    row = await cur.fetchone()
    await cur.close()
    used = row["overflow_daohang"] if row else 0
    grant = max(0, min(int(raw), settle.OVERFLOW_DAOHANG_WEEKLY_CAP - used))
    if grant <= 0:
        return 0
    await conn.execute(
        "INSERT INTO weekly_activity(user_id, week, overflow_daohang) VALUES(?,?,?) "
        "ON CONFLICT(user_id, week) DO UPDATE SET overflow_daohang=overflow_daohang+?",
        (user_id, week, grant, grant))
    return grant


async def _cap_regular_daohang(conn, user_id: int, raw: int, now: int) -> int:
    """#45 常规道行来源共用周上限，防历练/秘境等日常行为绕成无限水管。"""
    if raw <= 0:
        return 0
    week = _overflow_week(now)
    cur = await conn.execute(
        "SELECT regular_daohang FROM weekly_activity WHERE user_id=? AND week=?",
        (user_id, week))
    row = await cur.fetchone()
    await cur.close()
    used = row["regular_daohang"] if row else 0
    grant = max(0, min(int(raw), DAOHANG.REGULAR_WEEKLY_CAP - used))
    if grant <= 0:
        return 0
    await conn.execute(
        "INSERT INTO weekly_activity(user_id, week, regular_daohang) VALUES(?,?,?) "
        "ON CONFLICT(user_id, week) DO UPDATE SET regular_daohang=regular_daohang+?",
        (user_id, week, grant, grant))
    return grant


async def grant_regular_daohang_conn(conn, user_id: int, amount: int, event_type: str,
                                     now: int = None, realm: int = None) -> int:
    """给元婴及以上常规玩法发少量道行，并写 path_events（spec-v2 §4.3，#45）。"""
    now = int(time.time()) if now is None else now
    amount = int(amount or 0)
    if amount <= 0:
        return 0
    if realm is None:
        cur = await conn.execute("SELECT realm FROM characters WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return 0
        realm = row["realm"]
    if int(realm) < DAOHANG.UNLOCK_REALM:
        return 0
    grant = await _cap_regular_daohang(conn, user_id, amount, now)
    if grant <= 0:
        return 0
    await conn.execute(
        "UPDATE characters SET daohang=daohang+? WHERE user_id=?",
        (grant, user_id))
    await _add_daohang_event(conn, user_id, grant, event_type, now)
    return grant


async def grant_regular_daohang(user_id: int, amount: int, event_type: str,
                                now: int = None, realm: int = None) -> int:
    async with db.transaction() as conn:
        return await grant_regular_daohang_conn(conn, user_id, amount, event_type, now, realm)


async def touch_activity(user_id: int, username: str, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE tg_user_id=?", (user_id,))
        user = await cur.fetchone()
        await cur.close()
        if not user:
            return {"status": "missing"}

        auto_gain = 0
        row = await _select_character(conn, user_id)
        # 返回即自动收功：闲置超阈值时，把闲置那段直接结算成修为发给玩家，
        # 不把人留在闭关里（否则会挡住其本次想做的操作）；进行中的定时任务则避开。
        if row and not row["seclusion_at"]:
            last_seen = int(user["last_seen_at"] or user["created_at"] or now)
            if now - last_seen >= AUTO_SECLUSION_IDLE_SECONDS:
                settle_start = last_seen + AUTO_SECLUSION_IDLE_SECONDS
                welfare = await _sect_welfare(conn, user_id)
                state = json.loads(row["debuff_json"] or "{}")
                path_bonus = await dao_path.active_bonuses(user_id)
                asc_bonus = await ascension.passive_bonuses(user_id)
                outpost = await sect_war.bonuses_for_user(user_id)
                place_factor = 1 + clamp_seclusion_pct(
                    welfare["seclusion_pct"]
                    + raw_temporary_seclusion_pct(state, now)
                    + float(path_bonus.get("seclusion_pct", 0))
                    + float(asc_bonus.get("seclusion_pct", 0))
                    + float(outpost.get("seclusion_pct", 0)))
                windows = await activity.windows_for(user_id, settle_start, now, conn=conn)
                auto_gain, remainder = settle.seclusion_gain_with_remainder(
                    row["realm"], row["stage"], settle_start, now,
                    root_bone=row["root_bone"], place_factor=place_factor,
                    remainder_units=_seclusion_remainder(state, row["realm"], row["stage"]),
                    offline_cap_hours=settle.OFFLINE_CAP_HOURS + welfare["offline_extra_hours"],
                    activity_windows=windows,
                    active_factor=activity.SECLUSION_ACTIVE_FACTOR)
                _set_seclusion_remainder(state, row["realm"], row["stage"], remainder)
                new_cult, daohang, asc_pts = settle.overflow_split(
                    row["realm"], row["stage"], row["cultivation"], auto_gain)
                daohang = await _cap_overflow_daohang(conn, user_id, daohang, now)
                await _add_daohang_event(conn, user_id, daohang, "overflow", now)
                if asc_pts:
                    await ascension.add_points_conn(conn, user_id, asc_pts, now)
                await conn.execute(
                    "UPDATE characters SET cultivation = ?, daohang = daohang + ?, debuff_json = ? "
                    "WHERE user_id=?",
                    (new_cult, daohang, json.dumps(state, ensure_ascii=False), user_id))

        await conn.execute(
            "UPDATE users SET username=?, last_seen_at=? WHERE tg_user_id=?",
            (username, now, user_id))
        return {"status": "ok", "auto_cultivation": auto_gain}


def roll_root_bone(rng=random) -> int:
    return max(ROOT_BONE_MIN, min(ROOT_BONE_MAX, int(round(rng.gauss(60, 9)))))


async def create(user_id: int, username: str) -> Character:
    now = int(time.time())
    root = roll_root_bone(random)
    spirit = random.choice(SPIRIT_ROOTS)
    cap = R.STAMINA_CAP[0]
    async with db.transaction() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO users(tg_user_id, username, created_at, last_seen_at) "
            "VALUES(?,?,?,?)",
            (user_id, username, now, now))
        await conn.execute(
            "UPDATE users SET username=?, last_seen_at=? WHERE tg_user_id=?",
            (username, now, user_id))
        # OR IGNORE：并发双 /start 时不抛 IntegrityError，已存在则保留原存档。
        await conn.execute(
            "INSERT OR IGNORE INTO characters(user_id, root_bone, spirit_root, realm, stage, "
            "cultivation, stamina, stamina_at, seclusion_at, spirit_stone, weapon_key, created_at) "
            "VALUES(?,?,?,0,0,0,?,?,NULL,100,'新手剑',?)",
            (user_id, root, spirit, cap, now, now))
        await conn.execute(
            "INSERT OR IGNORE INTO character_skills(user_id, skill_key, slot) VALUES(?,?,0)",
            (user_id, STARTER_SKILL))
        await conn.execute(
            "INSERT OR IGNORE INTO character_skills(user_id, skill_key, slot) VALUES(?,?,?)",
            (user_id, STARTER_MIND, MIND_SLOT))
    return await get(user_id)


async def get(user_id: int):
    return await get_at(user_id)


async def get_at(user_id: int, now: int = None):
    row = await db.fetchone("SELECT * FROM characters WHERE user_id=?", (user_id,))
    if not row:
        return None
    now = int(time.time()) if now is None else now
    welfare = await sect_welfare(user_id)
    cap = R.STAMINA_CAP[row["realm"]] + welfare["stamina_bonus"]
    new_stam, new_at = settle.regen_stamina(row["stamina"], row["stamina_at"], cap, now)
    if new_stam != row["stamina"] or new_at != row["stamina_at"]:
        await db.execute("UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
                         (new_stam, new_at, user_id))
    return _from_row(row, new_stam, new_at)


async def stats(char: Character, equipped: list[dict] = None, pvp: bool = False) -> dict:
    base = R.base_stats(char.realm, char.stage)
    pct_bonus = {key: 0.0 for key in R.STAT_KEYS}
    # 道途/飞升/据点来源单独累加：PvP 下仅这部分折半（spec §6.3），装备/心法/福利/丹药不折半。
    pct_half = {key: 0.0 for key in R.STAT_KEYS}
    equipped = await equipped_items(char.user_id) if equipped is None else equipped
    if equipped:
        for inst in equipped:
            _apply_equipment_bonus(base, pct_bonus, equipment_bonus(inst), inst.get("enhance_level", 0))
        if not equipped_weapon_key(equipped):
            for k, v in weapon_bonus(char.weapon_key).items():
                base[k] = base.get(k, 0) + v
    else:
        for k, v in weapon_bonus(char.weapon_key).items():
            base[k] = base.get(k, 0) + v
    mind = await get_mind_skill(char.user_id)
    if mind:
        for key, val in skill_bonus(mind).items():
            if key.endswith("_pct"):
                stat_key = key[:-4]
                if stat_key in pct_bonus:
                    pct_bonus[stat_key] += float(val)
            else:
                base[key] = base.get(key, 0) + val
    for key, val in (await dao_path.active_bonuses(char.user_id)).items():
        if key.endswith("_pct"):
            stat_key = key[:-4]
            if stat_key in pct_half:
                pct_half[stat_key] += float(val)
        elif key in R.STAT_KEYS:
            base[key] = base.get(key, 0) + int(val)
    for key, val in (await ascension.passive_bonuses(char.user_id)).items():
        if key.endswith("_pct"):
            stat_key = key[:-4]
            if stat_key in pct_half:
                pct_half[stat_key] += float(val)
    outpost = await sect_war.bonuses_for_user(char.user_id)
    if outpost.get("stat_pct"):
        for key in R.STAT_KEYS:
            pct_half[key] += float(outpost["stat_pct"])
    _collect_temporary_stat_buffs(base, pct_bonus, char.debuff_json)
    welfare = await sect_welfare(char.user_id)
    if welfare["stat_pct"]:
        for key in R.STAT_KEYS:
            pct_bonus[key] += float(welfare["stat_pct"])
    _apply_stat_pct_bonus(base, pct_bonus, pct_half, pvp=pvp)
    unstable_until = int(char.debuff_json.get("unstable_until", 0))
    if unstable_until > int(time.time()):
        for key in R.STAT_KEYS:
            base[key] = max(1, int(base[key] * 0.9))
    return base


def settled_vitals(char: Character, max_hp: int, max_mp: int, now: int) -> tuple:
    """纯计算（不落库）：NULL⇒满、clamp 到 max（换装/降境致 max 下降）、按时间惰性回复。

    返回 (hp, hp_at, mp, mp_at)。供 vitals() 落库与 _resolve 战前取值复用。
    """
    cur_hp = max_hp if char.current_hp is None else max(0, min(char.current_hp, max_hp))
    cur_mp = max_mp if char.current_mp is None else max(0, min(char.current_mp, max_mp))
    new_hp, new_hp_at = settle.regen_resource(
        cur_hp, max_hp, char.hp_at or now, now, settle.HP_REGEN_SECONDS_PER_FULL)
    new_mp, new_mp_at = settle.regen_resource(
        cur_mp, max_mp, char.mp_at or now, now, settle.MP_REGEN_SECONDS_PER_FULL)
    return new_hp, new_hp_at, new_mp, new_mp_at


async def vitals(char: Character, now: int = None, stat_block: dict = None) -> dict:
    """当前/最大 气血法力，并把结算后的当前值惰性落库（仿 get_at 的精力落库）。

    返回 {"hp", "max_hp", "mp", "max_mp"}。供 /me、历练/秘境菜单使用（非写事务路径）。
    """
    now = int(time.time()) if now is None else now
    st = stat_block if stat_block is not None else await stats(char)
    max_hp, max_mp = st["hp"], st["mp"]
    hp, hp_at, mp, mp_at = settled_vitals(char, max_hp, max_mp, now)
    if (hp != char.current_hp or mp != char.current_mp
            or hp_at != char.hp_at or mp_at != char.mp_at):
        await db.execute(
            "UPDATE characters SET current_hp=?, current_mp=?, hp_at=?, mp_at=? WHERE user_id=?",
            (hp, mp, hp_at, mp_at, char.user_id))
    return {"hp": hp, "max_hp": max_hp, "mp": mp, "max_mp": max_mp}


def floor_hp(max_hp: int, end_hp: int) -> int:
    """活动结算写回的重伤地板：胜负都不破 20%·maxHP，且不超 max（#24）。"""
    return min(max_hp, max(int(max_hp * settle.HP_FLOOR_PCT), max(0, end_hp)))


async def write_vitals(user_id: int, hp: int, mp: int, now: int, conn=None):
    """活动结算后写回当前气血/法力（锚点重置为 now）。conn 给定则走写事务内。"""
    sql = ("UPDATE characters SET current_hp=?, current_mp=?, hp_at=?, mp_at=? "
           "WHERE user_id=?")
    params = (hp, mp, now, now, user_id)
    if conn is not None:
        await conn.execute(sql, params)
    else:
        await db.execute(sql, params)


def _apply_equipment_bonus(base: dict, pct_bonus: dict, bonus: dict, enhance_level: int = 0):
    # 强化只放大装备的「平加属性」（hp/atk/df/...），不放大百分比词条与战斗修正。
    for key, val in _enhanced_bonus_values(bonus, enhance_level).items():
        if key in COMBAT_MOD_KEYS:
            continue
        if key.endswith("_pct"):
            stat_key = key[:-4]
            if stat_key in pct_bonus:
                pct_bonus[stat_key] += float(val)
        else:
            base[key] = base.get(key, 0) + int(val)


def _collect_temporary_stat_buffs(base: dict, pct_bonus: dict, state: dict):
    for buff in active_temporary_buffs(state):
        for key, val in (buff.get("effects") or {}).items():
            if key.endswith("_pct"):
                stat_key = key[:-4]
                if stat_key in pct_bonus:
                    pct_bonus[stat_key] += float(val)
            elif key in R.STAT_KEYS:
                base[key] = base.get(key, 0) + int(val)


def _apply_stat_pct_bonus(base: dict, pct_bonus: dict, pct_half: dict = None, pvp: bool = False):
    # 非折半来源（装备/心法/福利/丹药）全额；折半来源（道途/飞升/据点）在 PvP ×PVP_PCT_FACTOR。
    # 两者累加后再统一 clamp 到分区上限（合算上限，spec §6.3）。
    factor = BUFFS.PVP_PCT_FACTOR if pvp else 1.0
    pct_half = pct_half or {}
    for key in pct_bonus:
        cap = _stat_pct_cap(key)
        raw = pct_bonus.get(key, 0.0) + pct_half.get(key, 0.0) * factor
        applied = min(cap, max(0.0, raw))
        if applied:
            base[key] = int(base.get(key, 0) * (1 + applied))


def _stat_pct_cap(key: str) -> float:
    if key in BUFFS.ATTACK_STATS:
        return BUFFS.ATTACK_PCT_CAP
    if key in BUFFS.SURVIVAL_STATS:
        return BUFFS.SURVIVAL_PCT_CAP
    return BUFFS.SURVIVAL_PCT_CAP


def equipment_bonus(inst: dict) -> dict:
    item = ITEMS.get(inst["base_key"], {})
    bonus = dict(item.get("bonus", {}))
    affixes = inst.get("affixes") or {}
    for key, val in affixes.items():
        bonus[key] = bonus.get(key, 0) + val
    return bonus


def _enhanced_bonus_values(bonus: dict, enhance_level: int = 0) -> dict:
    scaled = dict(bonus)
    lvl = int(enhance_level or 0)
    if lvl <= 0:
        return scaled
    mult = 1.0 + lvl * ENHANCE_PER_LEVEL
    for key, val in list(scaled.items()):
        if key in COMBAT_MOD_KEYS or key.endswith("_pct"):
            continue
        scaled[key] = int(round(val * mult))
    return scaled


def enhanced_equipment_bonus(inst: dict) -> dict:
    """返回强化后用于展示和属性结算的法宝增益。"""
    return _enhanced_bonus_values(equipment_bonus(inst), inst.get("enhance_level", 0))


async def combat_mods(user_id: int) -> dict:
    mods = {key: 0 for key in COMBAT_MOD_KEYS}
    for inst in await equipped_items(user_id):
        for key, val in (inst.get("affixes") or {}).items():
            if key in mods:
                mods[key] += val
    return mods


async def get_skills(user_id: int):
    rows = await db.fetchall(
        "SELECT skill_key FROM character_skills WHERE user_id=? AND slot>=0 ORDER BY slot",
        (user_id,))
    return [r["skill_key"] for r in rows]


async def get_mind_skill(user_id: int):
    row = await db.fetchone(
        "SELECT skill_key FROM character_skills WHERE user_id=? AND slot=?",
        (user_id, MIND_SLOT))
    return row["skill_key"] if row else None


async def knows_skill(user_id: int, skill_key: str) -> bool:
    row = await db.fetchone(
        "SELECT 1 FROM character_skills WHERE user_id=? AND skill_key=?",
        (user_id, skill_key))
    return row is not None


async def inventory(user_id: int, bound: int | None = None):
    if bound is None:
        rows = await db.fetchall(
            "SELECT item_key, SUM(qty) AS qty FROM inventory "
            "WHERE user_id=? AND qty>0 GROUP BY item_key ORDER BY item_key",
            (user_id,))
    else:
        rows = await db.fetchall(
            "SELECT item_key, qty FROM inventory "
            "WHERE user_id=? AND bound=? AND qty>0 ORDER BY item_key",
            (user_id, int(bool(bound))))
    return [(r["item_key"], r["qty"]) for r in rows]


async def item_instances(user_id: int):
    rows = await db.fetchall(
        "SELECT * FROM item_instances WHERE user_id=? ORDER BY equipped_slot DESC, id",
        (user_id,))
    return [_instance_from_row(row) for row in rows]


async def equipped_items(user_id: int):
    rows = await db.fetchall(
        "SELECT * FROM item_instances WHERE user_id=? AND equipped_slot IS NOT NULL ORDER BY id",
        (user_id,))
    return [_instance_from_row(row) for row in rows]


def equipped_weapon_key(equipped: list[dict]) -> str | None:
    for inst in equipped:
        if equipment_slot(inst["base_key"]) == "weapon":
            return inst["base_key"]
    return None


def current_weapon_key(char: Character, equipped: list[dict]) -> str:
    return equipped_weapon_key(equipped) or char.weapon_key


def _instance_from_row(row) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "base_key": row["base_key"],
        "tier": row["tier"], "equipped_slot": row["equipped_slot"],
        "affixes": json.loads(row["affixes_json"] or "{}"),
        "enhance_level": row["enhance_level"] if "enhance_level" in row.keys() else 0,
    }


async def item_qty(user_id: int, key: str, bound: int | None = None) -> int:
    if bound is None:
        row = await db.fetchone(
            "SELECT COALESCE(SUM(qty), 0) AS qty FROM inventory WHERE user_id=? AND item_key=?",
            (user_id, key))
    else:
        row = await db.fetchone(
            "SELECT qty FROM inventory WHERE user_id=? AND item_key=? AND bound=?",
            (user_id, key, int(bool(bound))))
    return row["qty"] if row else 0


async def add_item(user_id: int, key: str, qty: int, bound: int = 0):
    await db.execute(
        "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = MAX(0, qty + ?)",
        (user_id, key, int(bool(bound)), max(0, qty), qty))


async def item_qty_conn(conn, user_id: int, key: str, bound: int | None = None) -> int:
    if bound is None:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS qty FROM inventory WHERE user_id=? AND item_key=?",
            (user_id, key))
    else:
        cur = await conn.execute(
            "SELECT qty FROM inventory WHERE user_id=? AND item_key=? AND bound=?",
            (user_id, key, int(bool(bound))))
    row = await cur.fetchone()
    await cur.close()
    return row["qty"] if row else 0


async def consume_item_conn(conn, user_id: int, key: str, qty: int, bound: int | None = None) -> bool:
    qty = int(qty)
    if qty <= 0:
        return True
    have = await item_qty_conn(conn, user_id, key, bound)
    if have < qty:
        return False
    bounds = [int(bool(bound))] if bound is not None else [1, 0]
    left = qty
    for b in bounds:
        if left <= 0:
            break
        cur = await conn.execute(
            "SELECT qty FROM inventory WHERE user_id=? AND item_key=? AND bound=?",
            (user_id, key, b))
        row = await cur.fetchone()
        await cur.close()
        if not row or row["qty"] <= 0:
            continue
        used = min(left, row["qty"])
        await conn.execute(
            "UPDATE inventory SET qty=qty-? WHERE user_id=? AND item_key=? AND bound=?",
            (used, user_id, key, b))
        left -= used
    return True


async def add_stone(user_id: int, amount: int):
    await db.execute(
        "UPDATE characters SET spirit_stone = MAX(0, spirit_stone + ?) WHERE user_id=?",
        (amount, user_id))


async def spend_stone(user_id: int, amount: int) -> bool:
    async with db.transaction() as conn:
        row = await _select_character(conn, user_id)
        if not row or row["spirit_stone"] < amount:
            return False
        await conn.execute(
            "UPDATE characters SET spirit_stone = spirit_stone - ? WHERE user_id=?",
            (amount, user_id))
        return True


async def spend_stamina(user_id: int, amount: int):
    await db.execute(
        "UPDATE characters SET stamina = MAX(0, stamina - ?) WHERE user_id=?",
        (amount, user_id))


async def reserve_stamina_for_action(user_id: int, amount: int) -> dict:
    async with db.transaction() as conn:
        row = await _select_character(conn, user_id)
        if not row:
            return {"status": "missing"}
        now = int(time.time())
        welfare = await _sect_welfare(conn, user_id)
        stamina, stamina_at = _settled_stamina(row, now, welfare)
        if row["seclusion_at"]:
            if stamina != row["stamina"] or stamina_at != row["stamina_at"]:
                await conn.execute(
                    "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
                    (stamina, stamina_at, user_id))
            return {"status": "in_seclusion"}
        if stamina < amount:
            if stamina != row["stamina"] or stamina_at != row["stamina_at"]:
                await conn.execute(
                    "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
                    (stamina, stamina_at, user_id))
            return {"status": "no_stamina", "need": amount, "have": stamina}
        left = stamina - amount
        await conn.execute(
            "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?",
            (left, stamina_at, user_id))
        return {"status": "ok", "char": _from_row(row, left, stamina_at), "stamina_left": left}


async def set_cultivation(user_id: int, cultivation: int):
    await db.execute("UPDATE characters SET cultivation=? WHERE user_id=?",
                     (max(0, cultivation), user_id))


async def add_cultivation(user_id: int, amount: int):
    await db.execute(
        "UPDATE characters SET cultivation = MAX(0, cultivation + ?) WHERE user_id=?",
        (amount, user_id))


async def _create_item_instance_conn(conn, user_id: int, base_key: str,
                                     tier: str = None, affixes=None):
    item = ITEMS[base_key]
    tier = tier or item.get("tier", "凡")
    affixes_json = json.dumps(affixes or {}, ensure_ascii=False)
    await conn.execute(
        "INSERT INTO item_instances(user_id, base_key, tier, affixes_json) VALUES(?,?,?,?)",
        (user_id, base_key, tier, affixes_json))


async def create_item_instance(user_id: int, base_key: str, tier: str = None, affixes=None):
    async with db.transaction() as conn:
        await _create_item_instance_conn(conn, user_id, base_key, tier, affixes)


async def equip_instance(user_id: int, instance_id: int) -> dict:
    async with db.transaction() as conn:
        await _normalize_accessory_slots(conn, user_id)
        cur = await conn.execute(
            "SELECT * FROM item_instances WHERE id=? AND user_id=?", (instance_id, user_id))
        inst = await cur.fetchone()
        await cur.close()
        if not inst:
            return {"status": "not_found"}
        slot = equipment_slot(inst["base_key"])
        if not slot:
            return {"status": "not_equipment"}
        target_slot = slot
        if slot == "accessory":
            cur = await conn.execute(
                "SELECT equipped_slot FROM item_instances "
                "WHERE user_id=? AND equipped_slot IN ('accessory:1','accessory:2')",
                (user_id,))
            used = {row["equipped_slot"] for row in await cur.fetchall()}
            await cur.close()
            target_slot = next((s for s in ("accessory:1", "accessory:2") if s not in used),
                               "accessory:1")
        await conn.execute(
            "UPDATE item_instances SET equipped_slot=NULL WHERE user_id=? AND equipped_slot=?",
            (user_id, target_slot))
        await conn.execute(
            "UPDATE item_instances SET equipped_slot=? WHERE id=? AND user_id=?",
            (target_slot, instance_id, user_id))
        return {"status": "ok", "slot": target_slot, "name": item_name(inst["base_key"])}


async def _normalize_accessory_slots(conn, user_id: int):
    cur = await conn.execute(
        "SELECT id, equipped_slot FROM item_instances "
        "WHERE user_id=? AND equipped_slot IN ('accessory','accessory:1','accessory:2') "
        "ORDER BY id",
        (user_id,))
    rows = await cur.fetchall()
    await cur.close()
    used = set()
    updates = []
    for row in rows:
        current = row["equipped_slot"]
        if current in ("accessory:1", "accessory:2") and current not in used:
            target = current
        else:
            target = next((slot for slot in ("accessory:1", "accessory:2")
                           if slot not in used), None)
        if target:
            used.add(target)
        if target != current:
            updates.append((target, row["id"]))
    for target, item_id in updates:
        await conn.execute("UPDATE item_instances SET equipped_slot=? WHERE id=?", (target, item_id))


async def learn_skill_from_pages(user_id: int, page_key: str) -> dict:
    item = ITEMS.get(page_key, {})
    skill_key = item.get("skill")
    need = int(item.get("need", 0))
    if skill_key not in SKILLS:
        return {"status": "bad_page"}
    async with db.transaction() as conn:
        if not await consume_item_conn(conn, user_id, page_key, need):
            return {"status": "need_pages", "need": need, "have": await item_qty_conn(conn, user_id, page_key)}
        if is_mind_skill(skill_key):
            slot = MIND_SLOT
            cur = await conn.execute(
                "SELECT skill_key FROM character_skills WHERE user_id=? AND slot=?",
                (user_id, MIND_SLOT))
            current = await cur.fetchone()
            await cur.close()
            if current and current["skill_key"] == skill_key:
                return {"status": "known", "skill": skill_key}
            await conn.execute(
                "UPDATE character_skills SET skill_key=? WHERE user_id=? AND slot=?",
                (skill_key, user_id, MIND_SLOT))
            if not current:
                await conn.execute(
                    "INSERT OR IGNORE INTO character_skills(user_id, skill_key, slot) "
                    "VALUES(?,?,?)",
                    (user_id, skill_key, MIND_SLOT))
        else:
            cur = await conn.execute(
                "SELECT 1 FROM character_skills WHERE user_id=? AND skill_key=?",
                (user_id, skill_key))
            exists = await cur.fetchone()
            await cur.close()
            if exists:
                return {"status": "known", "skill": skill_key}
            cur = await conn.execute(
                "SELECT slot FROM character_skills WHERE user_id=? AND slot>=0 ORDER BY slot",
                (user_id,))
            used = {row["slot"] for row in await cur.fetchall()}
            await cur.close()
            slot = next((i for i in COMBAT_SLOTS if i not in used), 2)
            if slot in used:
                await conn.execute(
                    "UPDATE character_skills SET skill_key=? WHERE user_id=? AND slot=?",
                    (skill_key, user_id, slot))
            else:
                await conn.execute(
                    "INSERT INTO character_skills(user_id, skill_key, slot) VALUES(?,?,?)",
                    (user_id, skill_key, slot))
        return {"status": "ok", "skill": skill_key, "slot": slot}


async def add_prof(user_id: int, craft_type: str, amount: int):
    column = "alchemy_prof" if craft_type == "alchemy" else "forge_prof"
    await db.execute(
        f"UPDATE characters SET {column} = {column} + ? WHERE user_id=?",
        (amount, user_id))


async def set_progress(user_id: int, realm: int, stage: int, cultivation: int):
    await db.execute(
        "UPDATE characters SET realm=?, stage=?, cultivation=? WHERE user_id=?",
        (realm, stage, max(0, cultivation), user_id))


async def set_seclusion(user_id: int, ts):
    await db.execute("UPDATE characters SET seclusion_at=? WHERE user_id=?", (ts, user_id))


async def start_seclusion(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        row = await _select_character(conn, user_id)
        if not row:
            return {"status": "missing"}
        if row["seclusion_at"]:
            return {"status": "already"}
        welfare = await _sect_welfare(conn, user_id)
        stamina, stamina_at = _settled_stamina(row, now, welfare)
        await conn.execute(
            "UPDATE characters SET stamina=?, stamina_at=?, seclusion_at=? WHERE user_id=?",
            (stamina, stamina_at, now, user_id))
        return {"status": "started"}


async def collect_seclusion(user_id: int, now: int = None) -> dict:
    now = int(time.time()) if now is None else now
    async with db.transaction() as conn:
        row = await _select_character(conn, user_id)
        if not row:
            return {"status": "missing"}
        if not row["seclusion_at"]:
            return {"status": "not_in"}
        welfare = await _sect_welfare(conn, user_id)
        stamina, stamina_at = _settled_stamina(row, now, welfare)
        state = json.loads(row["debuff_json"] or "{}")
        path_bonus = await dao_path.active_bonuses(user_id)
        asc_bonus = await ascension.passive_bonuses(user_id)
        outpost = await sect_war.bonuses_for_user(user_id)
        place_factor = 1 + clamp_seclusion_pct(
            welfare["seclusion_pct"]
            + raw_temporary_seclusion_pct(state, now)
            + float(path_bonus.get("seclusion_pct", 0))
            + float(asc_bonus.get("seclusion_pct", 0))
            + float(outpost.get("seclusion_pct", 0)))
        cap_seconds = (settle.OFFLINE_CAP_HOURS + welfare["offline_extra_hours"]) * 3600
        window_end = min(now, int(row["seclusion_at"]) + cap_seconds)
        windows = await activity.windows_for(user_id, row["seclusion_at"], window_end, conn=conn)
        gained, remainder_units = settle.seclusion_gain_with_remainder(
            row["realm"], row["stage"], row["seclusion_at"], now,
            root_bone=row["root_bone"],
            place_factor=place_factor,
            remainder_units=_seclusion_remainder(state, row["realm"], row["stage"]),
            offline_cap_hours=settle.OFFLINE_CAP_HOURS + welfare["offline_extra_hours"],
            activity_windows=windows,
            active_factor=activity.SECLUSION_ACTIVE_FACTOR)
        _set_seclusion_remainder(state, row["realm"], row["stage"], remainder_units)
        new_cult, daohang, asc_pts = settle.overflow_split(
            row["realm"], row["stage"], row["cultivation"], gained)
        daohang = await _cap_overflow_daohang(conn, user_id, daohang, now)
        await _add_daohang_event(conn, user_id, daohang, "overflow", now)
        if asc_pts:
            await ascension.add_points_conn(conn, user_id, asc_pts, now)
        await conn.execute(
            "UPDATE characters SET cultivation=?, daohang=daohang+?, stamina=?, stamina_at=?, "
            "seclusion_at=NULL, debuff_json=? "
            "WHERE user_id=?",
            (new_cult, daohang, stamina, stamina_at, json.dumps(state, ensure_ascii=False), user_id))
        cost = R.advance_cost(row["realm"], row["stage"])
        return {"status": "collected", "gained": gained, "daohang": daohang,
                "ascension": asc_pts, "cultivation": new_cult,
                "cost": cost, "can_advance": new_cult >= cost,
                "minutes": max(0, (now - row["seclusion_at"]) // 60)}


async def _grant_reward_conn(conn, user_id: int, stone: int = 0,
                             cultivation: int = 0, drops: dict = None):
    await conn.execute(
        "UPDATE characters SET spirit_stone = MAX(0, spirit_stone + ?) WHERE user_id=?",
        (stone, user_id))
    if cultivation:
        # 发奖同样走溢出分流（#1）：化神圆满不再无限涨修为，越界转道行+飞升点。
        # 对非满级为 no-op（kept=cur+gain, daohang=0, asc=0），不改变既有发奖语义。
        cur = await conn.execute(
            "SELECT realm, stage, cultivation FROM characters WHERE user_id=?",
            (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if row:
            now = int(time.time())
            new_cult, daohang, asc_pts = settle.overflow_split(
                row["realm"], row["stage"], int(row["cultivation"] or 0), cultivation)
            daohang = await _cap_overflow_daohang(conn, user_id, daohang, now)
            await conn.execute(
                "UPDATE characters SET cultivation=?, daohang=daohang+? WHERE user_id=?",
                (new_cult, daohang, user_id))
            await _add_daohang_event(conn, user_id, daohang, "reward", now)
            if asc_pts:
                await ascension.add_points_conn(conn, user_id, asc_pts, now)
        else:
            await conn.execute(
                "UPDATE characters SET cultivation = MAX(0, cultivation + ?) WHERE user_id=?",
                (cultivation, user_id))
    for key, qty in (drops or {}).items():
        if qty <= 0:
            continue
        await conn.execute(
            "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,?) "
            "ON CONFLICT(user_id, item_key, bound) DO UPDATE SET qty = MAX(0, qty + ?)",
            (user_id, key, qty, qty))


async def grant_reward(user_id: int, stone: int = 0, cultivation: int = 0, drops: dict = None):
    async with db.transaction() as conn:
        await _grant_reward_conn(conn, user_id, stone, cultivation, drops)
