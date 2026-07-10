# Agent Notes

- Branch names: plain kebab-case, no agent/workflow prefix. `yuanying-huashen-pill-aid`, not `codex/yuanying-huashen-pill-aid`.
- PR titles: plain descriptive, no agent prefix. `add yuanying huashen pill aid`, not `[codex] add yuanying huashen pill aid`.
- Use `.venv` for test-related work.
- All user-facing strings, comments, docstrings: 中文. Match existing 修仙 tone.

## Stack
Python 3 + aiogram 3.x + SQLite (aiosqlite, WAL) + APScheduler. Async end-to-end. Single long-lived process: polling bot + in-process scheduler. No webhook, no worker, no queue.

## Layout
```
bot/        # entry: app.py (Dispatcher, ActivityMiddleware, scheduler jobs, _COMMANDS)
handlers/   # aiogram Routers, one per command domain  [has AGENTS.md]
services/   # business logic, async functions over DB    [has AGENTS.md]
config/     # static game data tables (realms, items…)   [has AGENTS.md]
models/     # db.py: SQLite access layer                  [has AGENTS.md]
tools/      # offline utilities (balance_sim)
tests/      # pytest + pytest-asyncio                     [has AGENTS.md]
docs/       # spec.md, spec-v2.md, plans/v2/, USER_GUIDE.md
spec.md / spec-v2.md  # game design source of truth
```

## Run / Test
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill BOT_TOKEN from @BotFather
python -m bot                 # canonical (polling). `python main.py` ≡ alias.
python -m pytest              # full suite (testpaths=tests)
python -m tools.balance_sim   # balance/economy regression report
```
SQLite auto-created at `data/xian.db` (gitignored). No CI, no Dockerfile, no Makefile.

**Testing discipline (required)**: after any code change, run the tests — and regress the full suite via `python -m pytest`, never just the touched file/case. Update the matching tests when behavior changes; commit only when everything is green. No CI backstop — a fully green local run is the only line of defense.

## Critical Conventions (project-wide)
- `from __future__ import annotations` first line of every module.
- Absolute imports only. No relative imports. Empty `__init__.py` in every package.
- Service aliasing on name collision: `from services import character as character_service`.
- Defense stat key is `df` (never `def` — Python keyword). `STAT_KEYS=("hp","mp","atk","df","spd","crit")`.
- `logging.getLogger("xian.<area>")` for service loggers.
- Realm index 0..5 = 炼气/筑基/金丹/元婴/化神/炼虚. Stage indexing per-realm.
- Code comments cite `spec §X.Y`, `#NN` (issue), `#AX` (audit) — preserve when editing.

## DB Layer (models/db.py) — Read First
- **Dual connection**: `_conn` (write, serialized via `_write_lock`) + `_read_conn` (WAL snapshot, `query_only=ON`).
- **Reads**: `await db.fetchone(sql, params)` / `db.fetchall(...)` (WAL-safe, lock-free).
- **Writes**: `await db.execute(sql, params)` (auto-commit, serialized) OR `async with db.transaction() as conn:` (`BEGIN IMMEDIATE`, rollback on raise).
- **Migrations**: additive via `_ensure_column(conn, table, col, def)` called inside `init_db()`. No Alembic. Destructive PK changes → write a `_migrate_*` helper (see `_migrate_inventory_bound`, `_migrate_sect_outposts_pk`).
- Schema lives in code as `SCHEMA` string; every table `CREATE IF NOT EXISTS`.

## Handler Conventions (see handlers/AGENTS.md)
- Each module: `router = Router()`. Wired in `bot/app.py` `_COMMANDS` + `dp.include_router(module.router)`.
- `cmd_<command>` / `cb_<action>`. Callbacks colon-namespaced: `nav:<feature>`, `ex:`, `dg:`, `asc:`, `craft:`, `shop:`, `market:`, `bt:`, `cult:`, `eq:`, `learn:`, `sectwar:`.
- **One-time callback tokens** (handlers/common.py): state-changing buttons MUST use `await action_callback_data(user_id, "prefix:action")` + `consume_action_callback(callback)`. TTL 15 min.
- Private-only gate: `await guard_private_message(message)` / `guard_private_callback(callback)`; returns True if rejected.
- Service calls return `dict` with `"status"` key; handler maps status → Chinese text (see `handlers/cultivate.py:_bt_text`).

## Service Conventions (see services/AGENTS.md)
- Async functions; private helpers prefixed `_`.
- **Lazy regen**: stamina/hp/mp recovered by timestamp delta on read, then persisted. Never precompute on timer.
- **Snapshot-at-departure**: combat/explore/dungeon settle on `start_hp`/`start_mp` snapshot. Late pill-use doesn't alter in-flight outcome.
- Return dicts use `"status"` vocabulary consumed by handlers.

## Config Conventions (see config/AGENTS.md)
- Pure data modules: dicts/lists/constants only. No DB, no async, no imports of services/handlers.
- Numeric tables indexed by realm 0..5.

## Test Conventions (see tests/AGENTS.md)
- pytest + pytest-asyncio. `@pytest.mark.asyncio` on async tests.
- Per-module `temp_db` fixture (no shared conftest fixtures beyond `sys.path` bootstrap).
- No `unittest.mock`. Use `monkeypatch`, deterministic in-test RNG (`StableRng`/`_FakeRng`), local fake bots (`FakeBot`/`FailingBot`/`FakeCallback`).

## Scheduler Jobs (bot/app.py)
- World Boss spawn: daily 20:00 (Asia/Shanghai).
- PvP weekly settle: Sun 23:55. Monthly season: last day 23:50. Sect-war season: last day 23:45.
- Token cleanup / market notify: every 1h. Activity cleanup: every 6h.
- Ready-action notify / social broadcast flush: every 1 min.

## Anti-patterns (this repo)
- Don't add `codex/`, `agent/`, `codex-` prefixes to branch names or PR titles.
- Don't bypass `_write_lock` — all writes go through `db.execute` or `db.transaction()`.
- Don't read vitals mid-battle to recompute — use the departure snapshot.
- Don't use bare `aiogram` callback strings for state-changing actions — wrap with `action_callback_data`.
- No `pyproject.toml`/ruff/mypy/pre-commit — don't introduce silently; discuss first.
