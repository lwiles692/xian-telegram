# services/ — business logic layer

Async functions over `models.db`. Each module owns one game system. Handlers call these; never the DB directly.

## Module Inventory (by domain)

**Character / growth** (largest cluster)
- `character.py` (899 lines, largest file) — registration, stats computation, inventory, lazy vitals regen, sect-welfare lookup. `Character` dataclass.
- `cultivation.py` — 闭关 (seclusion) start/collect, auto-seclusion after idle.
- `breakthrough.py` — small/big realm advancement, 天劫/神魂劫 tribulation flow, pill gating.
- `dao_path.py` (273 lines) — five 道途 (剑/体/丹/器/符阵), 道行 sinks, 转修令 switch.
- `ascension.py` — 飞升试炼 weekly trial, passive point allocation.
- `settle.py` — pure regen/settlement arithmetic (stamina/hp/mp by timestamp delta).

**Combat / PvE**
- `combat.py` — `Combatant` dataclass + `simulate(...)` deterministic battle engine (seeded).
- `explore.py` (473 lines) — 历练 map runs, encounter planning, mastery/sweep, departure snapshot.
- `dungeon.py` — 秘境 layered dungeon runs, boss floors.
- `world_boss.py` (399 lines) — scheduled spawn, group 合击, cultivator roster, reward tiers.
- `bosses.py` config — boss stat tables.

**Economy / crafting**
- `items.py` — inventory add/remove/query, bound-flag semantics.
- `equipment.py` — equip/unequip, enhance, reforge, decompose.
- `crafting.py` — 炼丹/炼器 jobs, recipe unlock, completion settle.
- `shop.py` — NPC buy/sell, daily-quota items.
- `market.py` — player 一口价坊市, tax, scheduled notify, bound-item blocklist.

**Social / group**
- `pvp.py` (314 lines) — group 切磋, ELO/天梯, weekly 声望 settle.
- `sect.py` — 宗门 create/join/donate/mission/shop/upgrade, welfare.
- `sect_war.py` — 据点战 outpost scoring, season settle.
- `season.py` — monthly season, 绑定称号 + 道行 rewards (idempotent).
- `social.py` — low-frequency broadcast queue, `flush_broadcasts(bot)` every 1 min.

**Loop / periodic**
- `daily.py` — 每日签到.
- `quests.py` — 悬赏任务 / 成就.
- `weekly_events.py` — 周活动 副本, 道行 reward caps.
- `activity.py` — `activity_windows` table management, `cleanup()` every 6h.
- `game_events.py` — low-frequency 奇遇 during explore.
- `notifications.py` — ready-action notifier (`notify_ready_actions(bot)` every 1 min).

## Conventions
- Public functions `async def snake_case(...)`. Internal helpers `_snake_case`.
- Return `dict` with `"status"` key (string); other keys carry payload. Handler maps status→text.
- **Lazy regen**: read path computes `stamina`/`hp`/`mp` from timestamp delta vs cap, persists updated value, updates `*_at` anchor. Don't schedule regen on a timer.
- **Snapshot-at-departure**: `explore_runs.start_hp`/`start_mp`/`dungeon_jobs.start_*` captured at run start; settlement uses snapshot, not current vitals. Late pill-use cannot rescue an in-flight run.
- **Aliasing on collision**: `from services import character as character_service`, `from services import explore as explore_service`, `from services import pvp as pvp_service`, `from services import sect_war as sect_war_service`, `from services import market as market_service`.
- **Spec citations**: comments cite `spec §X.Y`, `#NN` (issue), `#AX` (audit). Preserve when editing.
- **Idempotency**: weekly/monthly settles must be idempotent (re-running same period doesn't double-pay). See `season.settle_monthly`, `pvp.settle_weekly`, `sect_war.settle_season`.

## Combat Engine Calling Pattern
```python
from services.combat import Combatant, simulate
attacker = Combatant.from_stats(hp=..., atk=..., df=..., skills=[...], ...)
defender = Combatant.from_stats(...)
result = simulate(attacker, defender, seed=<int>)  # deterministic
# result: dict with status, log[], hp_after, ...
```
`tools/balance_sim.py` builds `Combatant` from realm-anchored stats; mirror its construction when adding new balance tests.

## Anti-patterns
- Don't write SQL from handlers — go through `services/*` → `models.db`.
- Don't bypass `_write_lock` / `db.transaction()` for multi-statement atomic flows.
- Don't recompute vitals mid-run from current state — use the stored snapshot.
- Don't return raw strings from services — return status dicts; text lives in handlers.
- Don't add weekly/monthly cron jobs without idempotency guard.
