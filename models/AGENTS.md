# models/ — SQLite access layer

Single module `db.py` (521 lines). All SQL in the codebase funnels through here. Read this before touching any persistence.

## Architecture: Dual Connection + Write Serialization
- `_conn` — write connection. `journal_mode=WAL`. All writes serialized through `_write_lock` (`asyncio.Lock`).
- `_read_conn` — read-only connection. `query_only=ON`. WAL snapshot isolation: never blocks writers, never reads dirty data.
- Rationale (spec §13/§14): prevent read/write deadlock on concurrent async handlers; guarantee atomic resource economy (spirit_stone, inventory).

## Lifecycle
- `await db.init_db(path=None)` — opens both connections, runs `SCHEMA` (`CREATE TABLE IF NOT EXISTS *`), runs `_ensure_column` migrations, opens `_read_conn`. Idempotent. Called once in `bot/app.py:main()` before scheduler/poller start.
- `await db.close_db()` — closes both conns, nulls globals. Called in `bot/app.py` `finally` block. Also called in every test `temp_db` fixture teardown.

## Query API
| Function | Use |
|----------|-----|
| `await db.fetchone(sql, params)` | single-row read (read conn, WAL snapshot) |
| `await db.fetchall(sql, params)` | multi-row read (read conn, WAL snapshot) |
| `await db.execute(sql, params)` | single write (acquires `_write_lock`, auto-commits) |
| `async with db.transaction() as conn:` | multi-statement atomic write (`BEGIN IMMEDIATE`, rollback on raise, holds lock for duration) |

Inside `transaction()`, use `conn.execute(...)` (not `db.execute`) to keep statements in the same transaction.

## Schema
- Defined in code as the `SCHEMA` string at top of `db.py`. ~20 tables: `users`, `characters`, `inventory`, `character_skills`, `item_instances`, `recipes_known`, `crafting_jobs`, `explore_runs`, `activity_windows`, `explore_mastery`, `dungeon_jobs`, `world_boss`, `pvp_ratings`, `sects`, `sect_members`, `sect_outposts`, `sect_donations`, `callback_tokens`, `market_listings`, `weekly_activity`, `ascension`, …
- All `CREATE TABLE IF NOT EXISTS` — safe on every boot.

## Migrations (no Alembic)
- **Additive column**: add to `SCHEMA` AND register an `_ensure_column(conn, table, col, "TYPE DEFAULT ...")` call inside `init_db()`. The `_ensure_column` helper introspects `PRAGMA table_info` and only runs `ALTER TABLE ADD COLUMN` if missing — safe for existing DBs.
- **Destructive change (PK reshape, type change)**: write a `_migrate_<thing>(conn)` helper. Pattern: create `<table>_new` with desired schema → `INSERT INTO _new SELECT ... FROM old` → `DROP old` → `RENAME _new TO old`. Must be idempotent (check current schema first; bail if already migrated). Examples: `_migrate_inventory_bound`, `_migrate_sect_outposts_pk`.
- **Adding a new table**: just append to `SCHEMA` (no migration needed — `CREATE IF NOT EXISTS`).
- All migrations run inside `init_db()` before `_read_conn` opens.

## Patterns to Follow
- Row access: `row = await db.fetchone("SELECT ... WHERE user_id=?", (user_id,))`. Columns via `row["col"]` (Row factory).
- Always close cursors: `cur = await conn.execute(...); ...; await cur.close()`.
- Multi-step stateful flow (check + deduct + reward): wrap in `async with db.transaction() as conn:` — prevents race where two callbacks both pass the check.
- Time columns: INTEGER unix timestamps. NULL sentinel often means "treat as now" (see `hp_at`/`mp_at`/`stamina_at`).

## Anti-patterns
- Don't open additional `aiosqlite.connect(...)` calls — bypasses WAL/lock guarantees. Use the two existing conns.
- Don't `db.execute` inside a `transaction()` block — double-lock deadlock. Use `conn.execute`.
- Don't read from `_conn` (write conn) when `_read_conn` suffices — defeats WAL isolation.
- Don't `ALTER TABLE` outside `init_db()` migrations — breaks idempotent boot.
- Don't introduce Alembic silently — migrations are intentionally code-embedded (spec design choice).
