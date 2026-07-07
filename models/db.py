"""SQLite 访问层：单连接 + WAL + 写串行化（spec §13/§14）。

约定（供后续模块复用）：
- 读用 ``fetchone`` / ``fetchall``（WAL 下并发读安全，无锁）。
- 写用 ``execute`` / ``executemany``（经 ``_write_lock`` 串行化，护灵石/库存等）。
- schema 启动时幂等建表。
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import aiosqlite

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "xian.db")
_conn = None          # 写连接：事务 / 写入，经 _write_lock 串行化
_read_conn = None     # 只读连接：WAL 快照读，永不取写锁，杜绝脏读与读-写死锁
_write_lock = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_user_id  INTEGER PRIMARY KEY,
    username    TEXT,
    created_at  INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS characters (
    user_id       INTEGER PRIMARY KEY,
    root_bone     INTEGER NOT NULL,
    spirit_root   TEXT NOT NULL,
    realm         INTEGER NOT NULL DEFAULT 0,
    stage         INTEGER NOT NULL DEFAULT 0,
    cultivation   INTEGER NOT NULL DEFAULT 0,
    stamina       INTEGER NOT NULL,
    stamina_at    INTEGER NOT NULL,
    seclusion_at  INTEGER,
    spirit_stone  INTEGER NOT NULL DEFAULT 0,
    weapon_key    TEXT NOT NULL DEFAULT '新手剑',
    alchemy_prof  INTEGER NOT NULL DEFAULT 0,
    forge_prof    INTEGER NOT NULL DEFAULT 0,
    debuff_json   TEXT NOT NULL DEFAULT '{}',
    stamina_buy_count   INTEGER NOT NULL DEFAULT 0,
    stamina_buy_day     TEXT,
    pill_stamina_count  INTEGER NOT NULL DEFAULT 0,
    pill_stamina_day    TEXT,
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
    user_id   INTEGER NOT NULL,
    item_key  TEXT NOT NULL,
    bound     INTEGER NOT NULL DEFAULT 0,
    qty       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_key, bound)
);
CREATE TABLE IF NOT EXISTS character_skills (
    user_id    INTEGER NOT NULL,
    skill_key  TEXT NOT NULL,
    slot       INTEGER NOT NULL,
    PRIMARY KEY (user_id, slot)
);
CREATE TABLE IF NOT EXISTS item_instances (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    base_key       TEXT NOT NULL,
    tier           TEXT NOT NULL,
    affixes_json   TEXT NOT NULL DEFAULT '{}',
    enhance_level  INTEGER NOT NULL DEFAULT 0,
    equipped_slot  TEXT
);
CREATE TABLE IF NOT EXISTS recipes_known (
    user_id     INTEGER NOT NULL,
    recipe_key  TEXT NOT NULL,
    PRIMARY KEY (user_id, recipe_key)
);
CREATE TABLE IF NOT EXISTS crafting_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    craft_type  TEXT NOT NULL,
    recipe_key  TEXT NOT NULL,
    start_at    INTEGER NOT NULL,
    finish_at   INTEGER NOT NULL,
    status      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS explore_runs (
    user_id    INTEGER PRIMARY KEY,
    map_key    TEXT NOT NULL,
    start_at   INTEGER NOT NULL,
    finish_at  INTEGER NOT NULL,
    seed       INTEGER NOT NULL,
    status     TEXT NOT NULL,
    encounters INTEGER NOT NULL DEFAULT 1,
    is_boss    INTEGER NOT NULL DEFAULT 0,
    event_key  TEXT,
    event_seed INTEGER,
    event_choice TEXT,
    notify_attempts INTEGER NOT NULL DEFAULT 0,
    notified_at INTEGER
);
CREATE TABLE IF NOT EXISTS activity_windows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    source_key  TEXT,
    start_at    INTEGER NOT NULL,
    finish_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_windows_user_time
ON activity_windows(user_id, finish_at, start_at);
CREATE TABLE IF NOT EXISTS explore_mastery (
    user_id          INTEGER NOT NULL,
    map_key          TEXT NOT NULL,
    consecutive_wins INTEGER NOT NULL DEFAULT 0,
    last_result_at   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, map_key)
);
CREATE TABLE IF NOT EXISTS dungeon_jobs (
    user_id     INTEGER PRIMARY KEY,
    dungeon_key TEXT NOT NULL,
    start_at    INTEGER NOT NULL,
    finish_at   INTEGER NOT NULL,
    seed        INTEGER NOT NULL,
    status      TEXT NOT NULL,
    notify_attempts INTEGER NOT NULL DEFAULT 0,
    notified_at INTEGER
);
CREATE TABLE IF NOT EXISTS dungeon_runs (
    user_id      INTEGER NOT NULL,
    dungeon_key  TEXT NOT NULL,
    day          TEXT NOT NULL,
    runs         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, dungeon_key, day)
);
CREATE TABLE IF NOT EXISTS pvp_ratings (
    user_id        INTEGER PRIMARY KEY,
    rating         INTEGER NOT NULL DEFAULT 1000,
    reputation     INTEGER NOT NULL DEFAULT 0,
    wins           INTEGER NOT NULL DEFAULT 0,
    losses         INTEGER NOT NULL DEFAULT 0,
    daily_count    INTEGER NOT NULL DEFAULT 0,
    daily_reset_at INTEGER NOT NULL DEFAULT 0,
    week_reputation INTEGER NOT NULL DEFAULT 0,
    week_tag       TEXT
);
CREATE TABLE IF NOT EXISTS pvp_daily_pairs (
    u1   INTEGER NOT NULL,
    u2   INTEGER NOT NULL,
    day  TEXT NOT NULL,
    PRIMARY KEY (u1, u2, day)
);
CREATE TABLE IF NOT EXISTS world_boss (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    boss_key      TEXT NOT NULL,
    total_hp      INTEGER NOT NULL,
    remaining_hp  INTEGER NOT NULL,
    spawn_at      INTEGER NOT NULL,
    expire_at     INTEGER NOT NULL,
    message_id    INTEGER,
    cultivator_count INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS world_boss_damage (
    boss_id  INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    damage   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (boss_id, user_id)
);
CREATE TABLE IF NOT EXISTS sects (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE,
    level              INTEGER NOT NULL DEFAULT 1,
    contribution_pool  INTEGER NOT NULL DEFAULT 0,
    leader_user_id     INTEGER NOT NULL,
    created_at         INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sect_members (
    sect_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    role          TEXT NOT NULL,
    contribution  INTEGER NOT NULL DEFAULT 0,
    donate_day    TEXT,
    donate_today  INTEGER NOT NULL DEFAULT 0,
    joined_at     INTEGER NOT NULL,
    PRIMARY KEY (user_id)
);
CREATE TABLE IF NOT EXISTS sect_tasks (
    user_id  INTEGER NOT NULL,
    day      TEXT NOT NULL,
    done     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS daily (
    user_id          INTEGER PRIMARY KEY,
    last_checkin_day TEXT,
    streak           INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quest_progress (
    user_id   INTEGER NOT NULL,
    quest_key TEXT NOT NULL,
    period    TEXT NOT NULL,
    progress  INTEGER NOT NULL DEFAULT 0,
    claimed   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, quest_key, period)
);
CREATE TABLE IF NOT EXISTS achievements (
    user_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS tribulation_sessions (
    user_id       INTEGER PRIMARY KEY,
    source_realm  INTEGER NOT NULL,
    source_stage  INTEGER NOT NULL,
    target_realm  INTEGER NOT NULL,
    target_stage  INTEGER NOT NULL,
    cultivation   INTEGER NOT NULL,
    cost          INTEGER NOT NULL,
    rate          REAL NOT NULL,
    guard_bonus   INTEGER NOT NULL DEFAULT 0,
    hp            INTEGER NOT NULL,
    thunder_index INTEGER NOT NULL DEFAULT 1,
    seed          INTEGER NOT NULL,
    log_json      TEXT NOT NULL DEFAULT '[]',
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS social_broadcasts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id        INTEGER,
    user_id        INTEGER NOT NULL,
    event_type     TEXT NOT NULL,
    text           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL,
    sent_at        INTEGER,
    next_attempt_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_social_broadcasts_pending
ON social_broadcasts(status, next_attempt_at, id);
CREATE TABLE IF NOT EXISTS social_broadcast_limits (
    user_id    INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    period     TEXT NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, event_type, period)
);
CREATE TABLE IF NOT EXISTS pvp_rank_snapshots (
    user_id      INTEGER PRIMARY KEY,
    tier         TEXT,
    top_rank     INTEGER,
    rating       INTEGER NOT NULL DEFAULT 1000,
    updated_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_chats (
    chat_id       INTEGER PRIMARY KEY,
    title         TEXT,
    last_seen_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_chat_members (
    chat_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    last_seen_at  INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS callback_tokens (
    token        TEXT PRIMARY KEY,
    user_id      INTEGER,
    action       TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    consumed_at  INTEGER
);
CREATE TABLE IF NOT EXISTS dao_paths (
    user_id     INTEGER NOT NULL,
    path_key    TEXT NOT NULL,
    xp          INTEGER NOT NULL DEFAULT 0,
    rank        INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 0,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, path_key)
);
CREATE TABLE IF NOT EXISTS path_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    path_key    TEXT,
    event_type  TEXT NOT NULL,
    amount      INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ascension (
    user_id     INTEGER PRIMARY KEY,
    level       INTEGER NOT NULL DEFAULT 0,
    points      INTEGER NOT NULL DEFAULT 0,
    spent_json  TEXT NOT NULL DEFAULT '{}',
    updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_activity (
    user_id     INTEGER NOT NULL,
    week        TEXT NOT NULL,
    runs        INTEGER NOT NULL DEFAULT 0,
    daohang     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, week)
);
CREATE TABLE IF NOT EXISTS sect_outposts (
    sect_id     INTEGER NOT NULL,
    outpost_key TEXT NOT NULL,
    score       INTEGER NOT NULL DEFAULT 0,
    season      TEXT NOT NULL,
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (sect_id, outpost_key)
);
CREATE TABLE IF NOT EXISTS pvp_season_rewards (
    user_id     INTEGER NOT NULL,
    season      TEXT NOT NULL,
    title       TEXT NOT NULL,
    daohang     INTEGER NOT NULL DEFAULT 0,
    claimed_at  INTEGER NOT NULL,
    PRIMARY KEY (user_id, season)
);
CREATE TABLE IF NOT EXISTS sect_war_rewards (
    season      TEXT NOT NULL,
    sect_id     INTEGER NOT NULL,
    score       INTEGER NOT NULL DEFAULT 0,
    settled_at  INTEGER NOT NULL,
    PRIMARY KEY (season)
);
CREATE TABLE IF NOT EXISTS market_listings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id   INTEGER NOT NULL,
    item_key    TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    price       INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    buyer_id    INTEGER,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS market_broadcast_state (
    chat_id          INTEGER PRIMARY KEY,
    last_notified_at INTEGER NOT NULL DEFAULT 0
);
-- 成交流水：每一笔成交（含部分购买）记一行，作为审计的不可变依据。
-- 挂单行会被部分购买改写 price/qty，无法据此还原交易额与频次，故独立记账。
CREATE TABLE IF NOT EXISTS market_trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id  INTEGER NOT NULL,
    seller_id   INTEGER NOT NULL,
    buyer_id    INTEGER NOT NULL,
    item_key    TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    price       INTEGER NOT NULL,
    tax         INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_listings_notify
ON market_listings(status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_market_trades_audit
ON market_trades(created_at, seller_id, buyer_id);
"""


async def init_db(path: str = None):
    global _conn, _read_conn, _write_lock
    db_path = path or _DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if _conn is not None:
        await _conn.close()
    if _read_conn is not None:
        await _read_conn.close()
    _conn = await aiosqlite.connect(db_path)
    _conn.row_factory = aiosqlite.Row
    _write_lock = asyncio.Lock()
    await _conn.execute("PRAGMA journal_mode=WAL;")
    await _conn.executescript(SCHEMA)
    await _ensure_column(_conn, "users", "last_seen_at", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "characters", "alchemy_prof", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "characters", "forge_prof", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "characters", "debuff_json", "TEXT NOT NULL DEFAULT '{}'")
    await _ensure_column(_conn, "characters", "stamina_buy_count", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "characters", "stamina_buy_day", "TEXT")
    await _ensure_column(_conn, "characters", "pill_stamina_count", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "characters", "pill_stamina_day", "TEXT")
    # 当前气血/法力（#24）：可空，NULL ⇒ 视为满（旧存档零回填；首次结算按当前 max 落地）。
    # hp_at/mp_at 为各自回复的惰性结算锚点，NULL ⇒ 视为 now（不补算历史回复）。
    await _ensure_column(_conn, "characters", "current_hp", "INTEGER")
    await _ensure_column(_conn, "characters", "current_mp", "INTEGER")
    await _ensure_column(_conn, "characters", "hp_at", "INTEGER")
    await _ensure_column(_conn, "characters", "mp_at", "INTEGER")
    await _ensure_column(_conn, "characters", "daohang", "INTEGER NOT NULL DEFAULT 0")
    # 溢出转道行的每周入账计量（周上限兜底，防满级挂机无限刷道行）。
    await _ensure_column(_conn, "weekly_activity", "overflow_daohang", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "world_boss", "message_id", "INTEGER")
    await _ensure_column(_conn, "world_boss", "cultivator_count", "INTEGER NOT NULL DEFAULT 1")
    await _ensure_column(_conn, "pvp_ratings", "reputation", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "pvp_ratings", "week_reputation", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "pvp_ratings", "week_tag", "TEXT")
    await _ensure_column(_conn, "item_instances", "enhance_level", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "sect_members", "donate_day", "TEXT")
    await _ensure_column(_conn, "sect_members", "donate_today", "INTEGER NOT NULL DEFAULT 0")
    # 迁移时留空(NULL)而非填默认值，使部署前的在途历练落入 _resolve 的"旧 run"兼容分支
    # （按 seed 还原旧规则的遭遇计划），不被静默改成 1 场非妖王。新 run 由 start() 显式写入。
    await _ensure_column(_conn, "explore_runs", "encounters", "INTEGER")
    await _ensure_column(_conn, "explore_runs", "is_boss", "INTEGER")
    await _ensure_column(_conn, "explore_runs", "notified_at", "INTEGER")
    await _ensure_column(_conn, "dungeon_jobs", "notified_at", "INTEGER")
    await _ensure_column(_conn, "explore_runs", "notify_attempts", "INTEGER NOT NULL DEFAULT 0")
    await _ensure_column(_conn, "dungeon_jobs", "notify_attempts", "INTEGER NOT NULL DEFAULT 0")
    # 出发时的血蓝快照（#24 P1）：战斗按出发状态结算，晚领/中途嗑丹不影响本场。
    # 旧在途 run 无快照(NULL) → _resolve 视作满血出发（兼容）。
    await _ensure_column(_conn, "explore_runs", "start_hp", "INTEGER")
    await _ensure_column(_conn, "explore_runs", "start_mp", "INTEGER")
    await _ensure_column(_conn, "explore_runs", "event_key", "TEXT")
    await _ensure_column(_conn, "explore_runs", "event_seed", "INTEGER")
    await _ensure_column(_conn, "explore_runs", "event_choice", "TEXT")
    await _ensure_column(_conn, "dungeon_jobs", "start_hp", "INTEGER")
    await _ensure_column(_conn, "dungeon_jobs", "start_mp", "INTEGER")
    await _ensure_column(_conn, "ascension", "last_trial_week", "TEXT")
    await _migrate_inventory_bound(_conn)
    await _migrate_sect_outposts_pk(_conn)
    await _conn.commit()
    # 独立只读连接：WAL 下读取已提交快照，不参与写锁，杜绝脏读与读-写死锁。
    _read_conn = await aiosqlite.connect(db_path)
    _read_conn.row_factory = aiosqlite.Row
    await _read_conn.execute("PRAGMA query_only=ON;")


async def close_db():
    global _conn, _read_conn, _write_lock
    if _conn is not None:
        await _conn.close()
        _conn = None
    if _read_conn is not None:
        await _read_conn.close()
        _read_conn = None
    _write_lock = None


def _c():
    assert _conn is not None, "DB 未初始化，请先 await init_db()"
    return _conn


def _rc():
    assert _read_conn is not None, "DB 未初始化，请先 await init_db()"
    return _read_conn


def _lock():
    assert _write_lock is not None, "DB 未初始化，请先 await init_db()"
    return _write_lock


async def _ensure_column(conn, table: str, column: str, definition: str):
    cur = await conn.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in await cur.fetchall()}
    await cur.close()
    if column not in columns:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def _migrate_inventory_bound(conn):
    cur = await conn.execute("PRAGMA table_info(inventory)")
    columns = {row[1] for row in await cur.fetchall()}
    await cur.close()
    if "bound" in columns:
        return
    await conn.execute(
        "CREATE TABLE inventory_new ("
        "user_id INTEGER NOT NULL, "
        "item_key TEXT NOT NULL, "
        "bound INTEGER NOT NULL DEFAULT 0, "
        "qty INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (user_id, item_key, bound))")
    await conn.execute(
        "INSERT INTO inventory_new(user_id, item_key, bound, qty) "
        "SELECT user_id, item_key, 0, qty FROM inventory")
    await conn.execute("DROP TABLE inventory")
    await conn.execute("ALTER TABLE inventory_new RENAME TO inventory")


async def _migrate_sect_outposts_pk(conn):
    """旧 sect_outposts 主键为 (sect_id)，导致一个宗门只能持 1 个据点。
    迁移为复合主键 (sect_id, outpost_key)，支持多据点并存。幂等可重入。"""
    cur = await conn.execute("PRAGMA table_info(sect_outposts)")
    info = await cur.fetchall()
    await cur.close()
    # pk 列（row[5]）：旧表仅 sect_id 为主键，outpost_key 的 pk==0 ⇒ 需迁移。
    pk_of = {row[1]: row[5] for row in info}
    if pk_of.get("outpost_key", 0) > 0:
        return
    await conn.execute(
        "CREATE TABLE sect_outposts_new ("
        "sect_id INTEGER NOT NULL, outpost_key TEXT NOT NULL, "
        "score INTEGER NOT NULL DEFAULT 0, season TEXT NOT NULL, updated_at INTEGER NOT NULL, "
        "PRIMARY KEY (sect_id, outpost_key))")
    await conn.execute(
        "INSERT INTO sect_outposts_new(sect_id, outpost_key, score, season, updated_at) "
        "SELECT sect_id, outpost_key, score, season, updated_at FROM sect_outposts")
    await conn.execute("DROP TABLE sect_outposts")
    await conn.execute("ALTER TABLE sect_outposts_new RENAME TO sect_outposts")


async def fetchone(sql, params=()):
    cur = await _rc().execute(sql, params)
    row = await cur.fetchone()
    await cur.close()
    return row


async def fetchall(sql, params=()):
    cur = await _rc().execute(sql, params)
    rows = await cur.fetchall()
    await cur.close()
    return rows


async def execute(sql, params=()):
    async with _lock():
        await _c().execute(sql, params)
        await _c().commit()


@asynccontextmanager
async def transaction():
    """串行化写事务；用于检查状态、扣资源、领奖励等原子流程。"""
    async with _lock():
        conn = _c()
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            await conn.rollback()
            raise
        else:
            await conn.commit()
