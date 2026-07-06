# handlers/ — aiogram Router layer

One Telegram command/callback domain per module. Thin: translate updates → service calls → Chinese text + inline keyboards.

## Module → Command → Service Map

| Module | Commands | Callback Prefix | Primary Service |
|--------|----------|-----------------|-----------------|
| `start.py` | `/start` | `nav:`, `start:` | `services.character` (register) |
| `me.py` | `/me` | `nav:me` | `services.character` |
| `cultivate.py` | `/cultivate` | `cult:`, `bt:do`, `bt:trib:` | `services.cultivation`, `services.breakthrough` |
| `explore.py` | `/explore` | `ex:` | `services.explore` |
| `dungeon.py` | `/dungeon` | `dg:` | `services.dungeon` |
| `craft.py` | `/craft` | `craft:` | `services.crafting` |
| `skills.py` | `/skills` | `eq:`, `learn:` | `services.equipment`, `services.items` |
| `shop.py` | `/shop` | `shop:` | `services.shop` |
| `bag.py` | `/bag` | `nav:bag`, `bag:` | `services.items` |
| `quest.py` | `/quest` | `nav:quest`, `quest:` | `services.quests` |
| `dao_path.py` | `/path` | `path:`, `nav:path` | `services.dao_path` |
| `ascension.py` | `/ascension` | `asc:` | `services.ascension` |
| `weekly_events.py` | `/weekly` | `we:`, `nav:weekly` | `services.weekly_events` |
| `market.py` | `/market` | `market:`, `nav:market` | `services.market` |
| `sect_war.py` | `/sectwar` | `sectwar:`, `nav:sectwar` | `services.sect_war` |
| `pvp.py` | `/pvp` | `pvp:` | `services.pvp` |
| `rank.py` | `/rank` | `nav:rank` | `services.pvp` |
| `boss.py` | `/boss` | `boss:` | `services.world_boss` |
| `sect.py` | `/sect` | `sect:`, `nav:sect` | `services.sect` |
| `daily.py` | `/daily` | `nav:daily` | `services.daily` |
| `help.py` | `/help` | `nav:help` | (static) |

## Registration Checklist (new handler)
1. Create `handlers/<feature>.py` with `router = Router()` at module top.
2. Define `cmd_<feature>(message)` + `cb_<action>(callback)` handlers; gate private-only with `guard_private_*`.
3. Add `BotCommand(...)` entry to `_COMMANDS` list in `bot/app.py`.
4. Add module import + `dp.include_router(module.router)` in `bot/app.py:main()`.
5. Wrap state-changing callbacks with `action_callback_data` / `consume_action_callback`.
6. Return `(text, markup)` pairs; render via `show(callback, text, markup)` for idempotent edit.

## common.py Helper Inventory
- **Callback tokens** (one-time, TTL 15 min): `action_callback_data(user_id, action)`, `consume_action_callback(callback)`, `cleanup_callback_tokens()`.
- **Guards**: `guard_private_message(message)`, `guard_private_callback(callback)`, `is_private_chat(chat)`, `dm_link(bot)`.
- **Menus**: `main_menu()`, `main_menu_return_button(text)`, `main_menu_return_markup(text)`, `append_main_menu_return(rows, text)`, `section_back_markup(text, cb, main_text)`, `button_grid(buttons, width)`, `menu_with_breakthrough(user_id, can_advance)`.
- **Vitals display**: `vitals_line(v)`, `battle_vitals_lines(res)`, `mp_starved_note(res)`, `progress_bar(cur, total, width)`.
- **Render**: `show(callback, text, markup)` — edits message; "not modified" silenced; un-editable falls back to `answer`.
- **Constants**: `NEED_START`, `PRIVATE_ONLY`, `TOKEN_EXPIRED`, `LOW_HP_PCT=0.30`, `LOW_MP_PCT=0.25`.

## Status → Text Pattern
Service returns `dict`; handler's `<feature>_text(res)` switches on `res["status"]` to produce Chinese string. Canonical example: `cultivate.py:_bt_text` (handles `need_cult` / `in_seclusion` / `missing` / `at_cap` / `need_pill` / `tribulation_choice` / `need_item` / `bad_action` / `no_tribulation` / `small_success` / `big_success` / `big_fail`).

## Anti-patterns
- Don't issue raw `callback_data` strings for state-changing actions — always one-time token.
- Don't query the DB directly from handlers — go through `services/*`.
- Don't construct menus by hand; reuse `common.py` builders for visual consistency.
- Don't answer callbacks twice — `show(...)` then `callback.answer()` exactly once per handler.
