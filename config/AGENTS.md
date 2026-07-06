# config/ — static game data tables

Pure data: dicts, lists, constants. No DB, no async, no imports of `services`/`handlers`/`models`. Numbers are tunable; referenced by services via `from config import <module> as <alias>`.

## Module Inventory

| Module | Contents |
|--------|----------|
| `realms.py` | `REALM_NAMES` (0..4), `REALM_STAGES`, `STAT_KEYS`, `BIG_BREAKTHROUGH` (pill/rate/tribulation per realm), `_ANCHORS` (stat ranges per realm/stage), `STAMINA_CAP`, `SECLUSION_STAGE_HOURS`. |
| `items.py` | `ITEMS` dict, `equipment_slot(key)`, `item_name(key)`, `weapon_bonus(key)`. |
| `equipment.py` | `ENHANCE_PER_LEVEL`, slot/affix tables. |
| `skills.py` | `SKILLS`, `COMBAT_SLOTS`, `MIND_SLOT`, `STARTER_SKILL`, `STARTER_MIND`, `skill_bonus`, `is_mind_skill`. |
| `maps.py` | `MAPS` (历练 maps per realm tier, encounter tables). |
| `dungeons.py` | `DUNGEONS` (秘境 layered defs). |
| `bosses.py` | `WORLD_BOSSES` (group boss tiers, stats, rewards). |
| `recipes.py` | 炼丹/炼器 recipes, unlock sources. |
| `shop.py` | `SHOP_ITEMS` (NPC stock, quotas, recycle prices). |
| `quests.py` | 悬赏 templates, achievement defs. |
| `dao_paths.py` | five 道途 (剑/体/丹/器/符阵), `RANK_NAMES`, rank bonuses. |
| `ascension.py` | `PASSIVE_CAP`, trial config, 飞升 reward table. |
| `buffs.py` | buff caps (`ATTACK_PCT_CAP`, `SURVIVAL_PCT_CAP`), buff sources. |
| `events.py` | `TRIBULATION_ACTIONS` (天劫/神魂劫 choices), random 奇遇 table. |
| `social.py` | social/broadcast rules, reputation caps. |
| `sects.py` | 宗门 levels, `welfare(level)` fn, donate rewards, mission table. |
| `sect_war.py` | 据点 outpost defs, scoring weights, season rewards. |
| `weekly_events.py` | 周活动 config (`RUN_DAOHANG_REWARD`, `RUN_STAMINA_COST`, `WEEKLY_DAOHANG_CAP`). |
| `copy.py` | UI copy / flavor text strings. |

## Conventions
- `from __future__ import annotations` first line.
- Module-level constants UPPER_SNAKE; lookup helpers `snake_case(key)`.
- Numeric tables indexed by realm `0..4` (炼气/筑基/金丹/元婴/化神) unless stated.
- Stat keys: `("hp","mp","atk","df","spd","crit")` — `df` not `def`.
- Tuning comments cite `spec §X.Y`, `#NN`, `#AX`. Preserve.

## Adding New Content
- **New item**: add to `ITEMS` in `items.py`; if equip, add slot mapping in `equipment_slot`; if crafted, add recipe to `recipes.py`.
- **New map/dungeon/boss**: add to `maps.py`/`dungeons.py`/`bosses.py`; realm-gate the unlock.
- **New skill**: add to `SKILLS` (`skills.py`); mark `is_mind_skill` if 心法; gate unlock source.
- **New realm tier**: extend `REALM_NAMES`, `_ANCHORS`, `STAMINA_CAP`, `SECLUSION_STAGE_HOURS`, `BIG_BREAKTHROUGH` in `realms.py`; add config across `dao_paths.py`/`ascension.py`/`bosses.py`/`dungeons.py`.
- Run `python -m tools.balance_sim` after numeric changes — regression report catches tuning drift.

## Anti-patterns
- No runtime mutation of config constants — treat as immutable.
- No DB queries, no async, no `services`/`handlers`/`models` imports (would create a cycle).
- No user-facing strings outside `copy.py` for new UI text (consolidate flavor there when practical).
- Don't edit numbers without checking `tools/balance_sim` output and spec citations.
