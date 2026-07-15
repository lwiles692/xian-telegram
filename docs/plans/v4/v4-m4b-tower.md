# V4-M4B 镇妖塔 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 1—100 层永久镇妖塔、事务内首通奖励、每日三败锁层和按本周新推进层数计算的群内周榜。

**Architecture:** 角色永久最高层存 `characters.tower_floor`；每次新高层在同一事务比较旧值并发首通奖励，同时 UPSERT 本周推进。周结算按群逐个开启独立事务，先插入 settlement 抢占权，再发奖和入队播报，单群失败不影响其他群。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、APScheduler、pytest、现有 combat/beast/social/RichPage。

---

## 一、文件结构

- Create: `config/tower.py` — 1—100 层配置、首通奖励、周榜奖励和数值分段。
- Modify: `config/items.py` — 镇妖塔奖励涉及的征途令/材料显示。
- Modify: `models/db.py` — tower 字段、日失败、周进度、结算和奖励表。
- Create: `services/tower.py` — 挑战、进度、排行、周结算。
- Modify: `services/social.py`、`config/social.py` — 百层首通与周榜播报入口。
- Create: `handlers/tower.py` — `/tower`、`tower:` callback、战报和多群榜单。
- Modify: `bot/app.py`、`handlers/common.py`、`config/copy.py`。
- Modify: `tools/balance_sim.py` — 1—100 层有兽/无兽矩阵。
- Create: `tests/test_tower_schema.py`、`tests/test_tower_challenge.py`、`tests/test_tower_weekly.py`、`tests/test_tower_handlers.py`、`tests/test_tower_balance.py`。
- Modify: `tests/test_playability_issues.py`、`tests/test_rich_pages.py`。
- Modify: `docs/plans/v4/m4-weekly-event-audit.md`、`docs/USER_GUIDE.md`。

---

## 二、必要的数据模型补充

spec-v4 的 `tower_daily` 只列 `fail_count`，无法区分“同一层连续失败”。实施时增加 `floor INTEGER NOT NULL DEFAULT 0`：挑战层变化时把 fail_count 重置为 0；只有同层失败才累加。

---

## 三、任务清单

### Task 1：建立 1—100 层配置和幂等 schema

**Files:**
- Create: `config/tower.py`
- Create: `tests/test_tower_schema.py`
- Modify: `models/db.py`
- Modify: `services/character.py`

- [ ] **Step 1：写层配置和 schema 失败测试**

测试 `TOWER_FLOORS` 恰有 100 层，key 为 1..100，怪物六维严格非降，首通奖励每层存在。层段目标：1—20 炼气/筑基，21—40 金丹/元婴，41—60 化神/炼虚，61—80 合体，81—100 合体圆满满配有兽。

测试角色 `tower_floor` 和四张表；`tower_daily` 包含额外 floor 列；所有索引与主键幂等。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tower_schema.py -v`

Expected: 配置和表缺失导致 FAIL。

- [ ] **Step 3：实现 config 数据生成**

`config/tower.py` 只依赖静态模板，不导入 service。使用五个 segment 的起止属性和线性插值生成 100 个固定 dict；每层保存 `name/mob/first_reward/repeat_reward/target_profile`。

奖励原则：1—20 基础绑定材料；21—40 稀有功法残页和首枚绑定缚灵索；41—60 炼虚材料和兽魂；61—80 合体材料、合体丹残方和神通残页占位；81—100 大机缘级绑定材料，100 层触发播报。

- [ ] **Step 4：增加 schema**

按 spec-v4 §7.5 建表；`tower_daily` 使用：

```sql
CREATE TABLE IF NOT EXISTS tower_daily (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    floor INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, day)
);
```

角色列 `tower_floor INTEGER NOT NULL DEFAULT 0` 同步加入 Character。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_tower_schema.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 1**

```bash
git add config/tower.py models/db.py services/character.py tests/test_tower_schema.py
git commit -m "建立镇妖塔配置与数据模型"
```

---

### Task 2：实现挑战、精力、灵兽与三败锁层

**Files:**
- Create: `services/tower.py`
- Create: `tests/test_tower_challenge.py`
- Modify: `services/beast.py`

**Interfaces:**

```python
async def overview(user_id: int, now: int | None = None) -> dict: ...
async def challenge(user_id: int, floor: int | None = None,
                    now: int | None = None, seed: int | None = None) -> dict: ...
```

- [ ] **Step 1：写挑战状态失败测试**

覆盖：炼气即可进入；默认挑战 `tower_floor+1`；不可越层；每次扣 5 精力；active beast 参战；同层连续败 3 次后当日 locked；换层/跨日重置；通过后 fail_count 清零；tower_floor 只进不退。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tower_challenge.py -v`

Expected: tower service 缺失导致 FAIL。

- [ ] **Step 3：实现挑战事务**

单事务读取角色、settled stamina、当前 vitals、tower_daily 和目标层；扣精力后构造 player、active support 和固定怪物，调用 `simulate(..., max_rounds=None, a_support=support)`；战斗结束写回 hp/mp，最低遵守现有重伤地板。

- [ ] **Step 4：实现失败计数**

若 day row 的 floor 与本次不同，先写 floor 和 fail_count=0。失败后 +1；达到 3 返回 `locked_today=True`。胜利后该 day row 置 fail_count=0。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_tower_challenge.py tests/test_combat.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 2**

```bash
git add services/tower.py services/beast.py tests/test_tower_challenge.py
git commit -m "实现镇妖塔挑战与锁层"
```

---

### Task 3：实现事务内首通奖励与本周推进

**Files:**
- Modify: `services/tower.py`
- Modify: `tests/test_tower_challenge.py`
- Modify: `services/game_events.py`
- Modify: `services/social.py`
- Modify: `config/social.py`

- [ ] **Step 1：写首通并发和重复挑战失败测试**

两个 fresh token 并发挑战同一新层，只允许一个事务观察到 `floor>old_floor` 并发首通奖励；另一个若仍完成战斗，只能得到 repeat_reward。重复挑战旧层不改变永久层数和周推进。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tower_challenge.py -k "first or concurrent or repeat" -v`

Expected: 首通逻辑缺失导致 FAIL。

- [ ] **Step 3：实现首通 CAS**

胜利后在同一事务重新读取 old floor；仅当目标 floor>old 时更新：

```sql
UPDATE characters SET tower_floor=?
WHERE user_id=? AND tower_floor<?;
```

rowcount=1 才发 first_reward，否则发 repeat_reward。禁止使用 game_flags。

- [ ] **Step 4：更新本周推进**

使用 Asia/Shanghai 周标签；new_progress=`target_floor-old_floor`。UPSERT：

```sql
progress = tower_week_progress.progress + excluded.progress,
reached_at = excluded.reached_at
```

仅新高层写入。100 层首通调用 `game_events.emit_conn(..., "tower.floor_100", ...)`，社交配置每日最多播报一次。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_tower_challenge.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 3**

```bash
git add services/tower.py services/game_events.py services/social.py config/social.py tests/test_tower_challenge.py
git commit -m "实现镇妖塔首通与周推进"
```

---

### Task 4：实现多群周榜读取与确定性并列排序

**Files:**
- Modify: `services/tower.py`
- Create: `tests/test_tower_weekly.py`

**Interfaces:**

```python
async def rankings_for_user(user_id: int, week: str | None = None) -> list[dict]: ...
async def ranking_for_chat(chat_id: int, week: str, limit: int = 10) -> list[dict]: ...
```

- [ ] **Step 1：写群成员过滤与并列失败测试**

测试只统计 `bot_chat_members` 当前已知成员；永久 floor 不参与排序；按 progress DESC、reached_at ASC、user_id ASC；同一玩家可出现在多个群。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tower_weekly.py -k ranking -v`

Expected: 排行接口缺失导致 FAIL。

- [ ] **Step 3：实现榜单查询**

SQL 连接 `tower_week_progress`、`bot_chat_members`、`users`、`characters`；返回本周推进、永久最高层、用户名和 reached_at。`rankings_for_user()` 先查用户所在群，再逐群查询，供私聊页面分节展示。

- [ ] **Step 4：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_tower_weekly.py -k ranking -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 4**

```bash
git add services/tower.py tests/test_tower_weekly.py
git commit -m "实现镇妖塔群内周榜"
```

---

### Task 5：实现周一幂等结算、奖励流水和群播报

**Files:**
- Modify: `services/tower.py`
- Modify: `services/social.py`
- Modify: `bot/app.py`
- Modify: `tests/test_tower_weekly.py`

- [ ] **Step 1：写周结算失败测试**

覆盖：`now-1秒` 确定上一周；前 3 名发绑定包；同一玩家多群可多领；重复执行不重复发；一个群故障回滚且其他群继续；修复后再次执行只重试失败群；播报只入队一次。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tower_weekly.py -k settle -v`

Expected: settle_weekly 缺失导致 FAIL。

- [ ] **Step 3：定义周奖励**

```python
WEEKLY_REWARDS = {
    1: {"bound_items": {"征途令": 2, "天材地宝": 3}},
    2: {"bound_items": {"征途令": 1, "天材地宝": 2}},
    3: {"bound_items": {"征途令": 1, "天材地宝": 1}},
}
```

- [ ] **Step 4：实现逐群事务**

`settle_weekly()` 先读取所有 bot_chats，再为每个 chat 调 `_settle_chat_weekly()`；内部先 `INSERT tower_weekly_settlements`，冲突直接 skipped；再写 reward rows、发绑定库存并调用新增 public `social.queue_group_broadcast_conn()`。

- [ ] **Step 5：注册调度**

在 `bot/app.py` 注册 Asia/Shanghai 周一 00:00；与周日 PvP 23:55 错开。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_tower_weekly.py tests/test_playability_issues.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 5**

```bash
git add services/tower.py services/social.py bot/app.py tests/test_tower_weekly.py tests/test_playability_issues.py
git commit -m "实现镇妖塔周榜幂等结算"
```

---

### Task 6：实现 `/tower` 页面、战报和群榜入口

**Files:**
- Create: `handlers/tower.py`
- Create: `tests/test_tower_handlers.py`
- Modify: `handlers/common.py`
- Modify: `bot/app.py`
- Modify: `config/copy.py`
- Modify: `tests/test_rich_pages.py`

- [ ] **Step 1：写 handler 和 token 失败测试**

测试 private-only；挑战和重温按钮使用一次性 `tower:` token；显示永久层数、本周推进、当日失败次数；锁层时不生成挑战按钮；榜单按群分节。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tower_handlers.py -v`

Expected: handler 不存在导致 FAIL。

- [ ] **Step 3：实现命令和路由**

注册 `/tower`，主菜单按钮“🗼 镇妖塔”，帮助页放入“历练斗法”。默认挑战下一层；已通关层只提供“重温当前最高层”，奖励标注为轻量重复奖励。

- [ ] **Step 4：实现 Rich 战报**

胜负、首通/重温、奖励、当前气血法力、剩余精力和永久层数放在折叠区外；回合日志折叠。100 层首通文案保持克制，不使用大量 emoji。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_tower_handlers.py tests/test_rich_pages.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 6**

```bash
git add handlers/tower.py handlers/common.py bot/app.py config/copy.py tests/test_tower_handlers.py tests/test_rich_pages.py
git commit -m "开放镇妖塔挑战与群榜"
```

---

### Task 7：校准 1—100 层并完成负担审计

**Files:**
- Modify: `tools/balance_sim.py`
- Create: `tests/test_tower_balance.py`
- Modify: `config/tower.py`
- Modify: `docs/plans/v4/m4-weekly-event-audit.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1：写全层 profile 失败测试**

对每层读取 target_profile，断言目标档满 buff 有兽成功率处于“刚好可刷”区间 55%—90%；对应无兽档成功率不低于 10%；低一档不得稳定通过。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tower_balance.py -v`

Expected: balance 接口或初版数值不达标导致 FAIL。

- [ ] **Step 3：实现全层报告并定参**

报告按 10 层分组输出目标有兽、无兽和低一档结果；迭代 `config/tower.py` segment 曲线，不在测试中放宽阈值掩盖越线。

- [ ] **Step 4：完成周事件总量审计**

在 M4A 审计文件追加镇妖塔：无每日任务奖励，失败三次锁层，重复奖励极轻；建议玩家有明显战力提升时再挑战。与征途合计新增每日主动操作目标低于 5 分钟。

- [ ] **Step 5：完整验收**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 100 层全部档位通过，无兽玩家不被完全拒绝。

- [ ] **Step 6：更新指南并提交 Task 7**

```bash
git add tools/balance_sim.py config/tower.py tests/test_tower_balance.py docs/plans/v4/m4-weekly-event-audit.md docs/USER_GUIDE.md
git commit -m "校准镇妖塔全层门槛"
```

---

## 四、M4B 完成定义

1. 永久 tower_floor 只增不减，首通奖励只发一次。
2. 同层连续三败当日锁定，跨日/换层规则正确。
3. 本周推进只统计新高层，群榜过滤成员并确定性排序。
4. 周结算按群幂等，多群玩家可多群获奖，单群失败可重试。
5. 灵兽参与挑战，1—100 层有兽/无兽平衡矩阵通过。
6. M4 总新增每日主动操作审计低于 5 分钟。
7. 全量测试与 balance_sim 通过。
