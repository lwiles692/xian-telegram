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
manual/     # Hexo 静态玩家手册（全书 31 章，站内构建: `cd manual && npx hexo generate`）
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

## 消息展示与文案规范

- 消息按信息密度分层：一句话成功、失败、资源不足、冷却和令牌提示使用 `str`；角色面板、商店、悬赏等交互页面使用 aiogram `Text` 实体；帮助、版本公告、历练/秘境/PvP 结算等长报告使用 `RichPage`。
- 统一通过 `bot.presentation.answer()`、`show()`、`send()` 发送、编辑或主动播报。`RichPage` 必须同时提供 Rich HTML 与语义一致的 `Text` 回退；不要在 handler 中直接拼发送参数，也不要为两种格式重复查询业务数据。
- 普通实体消息禁止依赖全局 `parse_mode`，发送参数必须显式保持 `parse_mode=None`。Rich 页面只使用 Rich HTML，不使用 Markdown/MarkdownV2。
- Rich HTML 中所有玩家名、宗门名、物品名、战斗日志和其他外部或动态文本必须经过 `escape_rich_html()`；静态标签集中在展示构造器中生成，禁止手写未转义的动态 HTML。
- 长文首行使用粗体标题，核心状态紧跟标题；用真正的小节标题和空行表达层级，禁止用 `—— 标题 ——` 一类字符横线充当分隔线。列表每行只表达一个对象，编号、物品名或角色名作为视觉锚点。
- 规则说明使用斜体或引用，操作提示放在末尾；已有按钮能表达的动作不再重复成长句。每个小节最多使用一个功能性 emoji，保持修仙口吻但避免满屏装饰。
- 战报的胜负、奖励、当前气血法力和剩余精力必须保持在折叠区外；逐回合日志放入 Rich HTML 的 `<details>`，实体回退使用 `ExpandableBlockQuote`。日志为空时显示“斗法无可记述。”。PvP 战报必须明确“本场不消耗气血、法力与精力”。
- `RICH_MESSAGES_ENABLED` 默认开启，仅 `1`、`true`、`yes`、`on`（忽略大小写）视为开启；关闭时直接发送实体回退。Rich 解析失败或明确不支持 Rich 的 Telegram 错误才允许降级，`message is not modified` 静默处理，未知、限流和网络异常继续抛出。
- Rich 与普通消息切换时，按钮文字、callback 数据和一次性令牌行为必须保持不变；状态变更按钮仍遵守 `action_callback_data()` / `consume_action_callback()` 规则。

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

## Documentation Discipline
- 游戏机制后续有变动时（新增/调整境界、地图、秘境、物品、配方、玩法规则、指令等），必须**马上同步更新** `manual/` 下对应的玩家手册章节（Hexo 源文在 `manual/source/_posts/`、目录在 `manual/source/menu.md`），并重新 `cd manual && npx hexo generate` 构建验证。手册是玩家权威参考，与实现脱节即为缺陷。
