# V3-M1 完成审计

审计日期：2026-07-09

审计范围：`v3-m1-lianxu-loop.md` 全部任务与 M1 DoD。结论仅基于当前仓库文件、测试与 `tools.balance_sim` 输出，不使用口头记忆作证。

## 任务验收

| 任务 | 要求 | 当前证据 | 结论 |
|---|---|---|---|
| T1.1 虚空神殿 | `xukong` 秘境、6 层、70 精力、4000 入场、每日 2 次、炼虚材料与白名单掉落；入门推进 40%~70%、圆满稳定通关、经济不套利 | `config/dungeons.py`；`tests/test_lianxu_loop.py::test_xukong_dungeon_config_complete`、`test_xukong_entry_and_full_clear_fraction_targets`、`test_xukong_dungeon_economy_stays_under_lianxu_buy_margin` | 已完成 |
| T1.2 炼虚世界 Boss | `WORLD_BOSSES["lianxu"]`、`_REALM_TIER[5]`、20~80 总挑战、小群缩放、无完整炼虚丹参与奖 | `config/bosses.py`；`tests/test_lianxu_loop.py::test_lianxu_world_boss_config_complete`、`test_lianxu_world_boss_kill_challenges_target_range`、`test_lianxu_world_boss_tier_and_small_group_scaling` | 已完成 |
| T1.3 炼虚装备 / 材料 / 炼制链 | 三件炼虚装备、残页合成图纸、三图独占材料进配方、来源覆盖秘境/Boss/难图、材料可交易 | `config/items.py`、`config/recipes.py`；`tests/test_lianxu_loop.py::test_lianxu_equipment_configs_and_recipes_exist`、`test_lianxu_equipment_sources_include_dungeon_boss_and_hard_map`、`test_lianxu_blueprint_scraps_unlock_and_forge_equipment` | 已完成 |
| T1.4 `LIANXU_GEARED` 回归 | 新增炼虚装备档；三图、虚空神殿、炼虚 Boss 均按该档固定；保留化神满 buff 上界护栏 | `tools/balance_sim.py`；`tests/test_balance.py::test_lianxu_geared_hits_map_gates`、`test_huashen_full_buff_cannot_break_lianxu_boss_gates`、`tests/test_lianxu_loop.py::test_lianxu_equipment_profile_keeps_anchor_headroom` | 已完成 |
| T1.5 数值定稿与白名单反套利 | 怪物/掉落数值落区间；白名单材料按可交易口径进入反套利；炼虚日常精力自洽 | `tools/balance_sim.py::best_content_market_value_per_stamina`、`lianxu_daily_loop_profile`；`tests/test_balance.py::test_auction_whitelist_material_values_stay_under_buy_margin`、`test_lianxu_daily_loop_stamina_and_market_value_are_self_consistent`；`docs/plans/v3/m1-weekly-event-audit.md` | 已完成 |
| T1.6 心魔劫 | `reward_flag` 迁移；三类交互式天劫出现「直面心魔」；本段无减伤；成功发道心通明 + 道行 + 播报；失败额外扣 5% 当前修为 + 播报；buff 进 clamp | `config/events.py`、`models/db.py`、`services/breakthrough.py`；`tests/test_heart_tribulation.py`；`tests/test_buff_caps.py::test_daoxin_tongming_seclusion_buff_enters_clamp` | 已完成 |

## DoD 核对

| DoD | 当前证据 | 结论 |
|---|---|---|
| `python -m pytest` 全绿；炼虚门槛/秘境/Boss/装备测试基于 `LIANXU_GEARED` 齐备 | 本轮使用 `.venv/bin/python -m pytest` 回归；相关测试集中在 `tests/test_balance.py`、`tests/test_lianxu_loop.py`、`tests/test_heart_tribulation.py` | 满足 |
| `python -m tools.balance_sim`：炼虚全内容数值落区间，套利全堵（含白名单材料） | `tools.balance_sim` 报告包含 M1 炼虚装备档、T1.5 日常闭环、白名单材料折算；当前输出显示炼虚白名单折算 `221.3/225.0` | 满足 |
| 炼虚日常闭环成立：三图历练 + 虚空神殿 ×2 + 炼虚 Boss，精力 280 分配自洽 | `tools.balance_sim.lianxu_daily_loop_profile()`；报告显示日常精力 `232/280` | 满足 |
| schema 仅 `_ensure_column` 加列 `reward_flag` | `models/db.py` 在 `tribulation_sessions` schema 与 `init_db()` 中新增 `reward_flag TEXT`；`tests/test_heart_tribulation.py::test_heart_reward_flag_migration_is_idempotent` | 满足 |
| 周事件总量审计：虚空神殿/炼虚 Boss 为存量日常境界平移，非新增周必做；审计表存档 | `docs/plans/v3/m1-weekly-event-audit.md` | 满足 |

## 收口结论

M1 的炼虚 PvE、装备链、数值回归、经济护栏与心魔劫均有当前仓库证据支撑。下一阶段可按 `v3-m2-auction.md` 开始拍卖行独立开发；M2 仍需复用 T1.5 白名单材料反套利档口作为回归护栏。
