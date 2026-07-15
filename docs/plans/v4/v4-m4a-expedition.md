# V4-M4A 征途模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付金丹起解锁的四档 Roguelike 征途，以征途令限频，支持稳定门选择、run 内临时增益、灵兽参战、奇遇复用、见好就收和失败惩罚。

**Architecture:** `expedition_runs` 保存一次 run 的全部可恢复状态；每层门在生成后写入 `current_doors`，刷新页面不重新 roll。层结算通过 `floor_settled=0` 条件抢占；宝门/精英门的碎片选择作为同一 run 的子阶段保存。所有累计奖励到退出时一次性绑定发放。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、pytest、现有 combat/adventure/beast/RichPage。

---

## 一、文件结构

- Modify: `config/dungeons.py` — `EXPEDITION_TIERS`、门权重、怪物池和奖励表。
- Modify: `config/items.py` — 征途令与道器碎片展示名。
- Modify: `config/maps.py`、`config/bosses.py`、`config/quests.py`、`services/daily.py` — 征途令来源。
- Modify: `models/db.py` — `expedition_runs` 与 active unique index。
- Create: `services/expedition.py` — start/render/choose/shard/retire/finalize。
- Modify: `services/adventure.py` — expedition reward sink 与遇门完成回调。
- Modify: `services/character.py`、`handlers/skills.py` — 提前掉落神通残页的 feature_pending 防误用。
- Modify: `services/character.py`、`services/explore.py`、`services/dungeon.py`、`services/items.py`、`services/cultivation.py` — active expedition 冲突检查。
- Create: `handlers/expedition.py` — `/venture`、`exp:` callback 和 Rich 结算。
- Modify: `handlers/adventure.py`、`handlers/common.py`、`bot/app.py`、`config/copy.py`。
- Modify: `tools/balance_sim.py` — 四档征途门槛和奖励价值。
- Create: `tests/test_expedition_schema.py`、`tests/test_expedition_run.py`、`tests/test_expedition_doors.py`、`tests/test_expedition_buffs.py`、`tests/test_expedition_adventure.py`、`tests/test_expedition_handlers.py`、`tests/test_expedition_balance.py`。
- Modify: `tests/test_vitals.py`、`tests/test_playability_issues.py`、`tests/test_rich_pages.py`。
- Create: `docs/plans/v4/m4-weekly-event-audit.md`。
- Modify: `docs/USER_GUIDE.md`。

---

## 二、状态约定

`current_doors` JSON 同时保存层选择阶段：

```python
{
    "phase": "choose_door",  # choose_door | choose_shard | adventure
    "floor": 3,
    "doors": [
        {"index": 0, "type": "battle", "seed": 101, "label": "战门"},
        {"index": 1, "type": "treasure", "seed": 102, "label": "宝门"},
    ],
    "selected": None,
    "shard_options": [],
    "adventure_choice_id": None,
}
```

`rewards` 保存未发放的绑定奖励；不保存灵石。`buffs` 保存最多三个道器碎片和歧路对下一层的权重修正。

---

## 三、任务清单

### Task 1：增加征途配置、令牌来源和 schema

**Files:**
- Modify: `config/dungeons.py`
- Modify: `config/items.py`
- Modify: `config/maps.py`
- Modify: `config/bosses.py`
- Modify: `config/quests.py`
- Modify: `services/daily.py`
- Modify: `models/db.py`
- Create: `tests/test_expedition_schema.py`

- [ ] **Step 1：写配置与 schema 失败测试**

测试四档：

```python
EXPECTED = {
    "dongtian": {"realm": 2, "floors": 6},
    "secret": {"realm": 3, "floors": 8},
    "forbidden": {"realm": 5, "floors": 10},
    "void": {"realm": 6, "floors": 12},
}
```

门基础权重固定 battle 35、elite 15、treasure 25、adventure 15、rest 5、fork 5；每档可覆盖但总和必须 100。

测试 `expedition_runs` 全部 spec 列和 partial unique index。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_schema.py -v`

Expected: 配置、物品和表缺失导致 FAIL。

- [ ] **Step 3：增加征途令与配置**

`征途令` 为绑定、不可交易的 material。`EXPEDITION_TIERS` 每档包含 realm、floors、door_weights、mob_pool、elite_pool、reward_pool、adventure_rarities。

道器碎片 key 固定：`barrier_breaker`、`body_screen`、`speed_order`、`spirit_orb`、`lifesaver`。

同时预置八种绑定神通残页 item，统一 `type='page'`、`need=3`、`feature_pending=True`。其中禁地层宝门可低概率产出 `噬魂火残页`，天外层精英门可低概率产出 `星渊破残页`；M6B 前 `learn_skill_from_pages()` 必须在扣页前返回 `feature_pending`，handler 显示封印文案。其余六种残页先只建物品定义，来源由 M4B/M6B 接入。

- [ ] **Step 4：增加稳定来源**

- 九天玄宫掉落 `征途令` 8%。
- 噬星古鲲前列总池 2 枚。
- 连续签到每第 7 日额外发绑定征途令×1。
- `weekly_dungeon` 悬赏奖励追加绑定征途令×1。
- 镇妖塔首通来源在 M4B 接入。

- [ ] **Step 5：增加 schema**

严格按 spec-v4 §6.7 建表，`status` 只允许 active/done；active unique index 确保同时仅一 run。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_expedition_schema.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 1**

```bash
git add config/dungeons.py config/items.py config/maps.py config/bosses.py config/quests.py services/daily.py services/character.py handlers/skills.py models/db.py tests/test_expedition_schema.py
git commit -m "建立征途配置与运行数据模型"
```

---

### Task 2：实现入口、快照、活动互斥和稳定门生成

**Files:**
- Create: `services/expedition.py`
- Create: `tests/test_expedition_run.py`
- Create: `tests/test_expedition_doors.py`
- Modify: `services/character.py`
- Modify: `services/explore.py`
- Modify: `services/dungeon.py`
- Modify: `services/items.py`
- Modify: `services/cultivation.py`

**Interfaces:**

```python
async def active_run(user_id: int) -> dict | None: ...
async def start(user_id: int, now: int | None = None, rng=None) -> dict: ...
async def overview(user_id: int) -> dict: ...
```

- [ ] **Step 1：写入口和互斥失败测试**

覆盖：金丹以下 locked；自动选择当前境界最高档；无令牌拒绝；无每日次数列与限制；并发 start 只有一条 active；历练/秘境/闭关中拒绝；active expedition 时历练、秘境、闭关、恢复丹均返回 busy_expedition。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_run.py -v`

Expected: service 缺失导致 FAIL。

- [ ] **Step 3：实现 start 事务**

事务内检查角色、现有前台活动、active run 和令牌；扣 1 枚绑定优先的征途令；按出发时 settled vitals 写 hp/mp snapshot 和 current 值；run seed 由 rng 生成；floor=1；立即生成并持久化首层门。

- [ ] **Step 4：实现确定性门生成**

```python
def generate_doors(tier: str, floor: int, run_seed: int,
                   route_modifier: str | None = None) -> list[dict]: ...
```

随机源固定 `random.Random(f"{run_seed}:{tier}:{floor}:{route_modifier}")`；门数 2 或 3；同层至少两个不同门型；重新 overview 只读取 current_doors，不调用生成器。

- [ ] **Step 5：扩展 busy 检查**

`character._has_active_job()`、历练/秘境 start、闭关 start 和恢复丹 busy SQL 加 `EXISTS expedition_runs status='active'`。征途结束前不允许外部恢复覆盖 run snapshot。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_expedition_run.py tests/test_expedition_doors.py tests/test_vitals.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 2**

```bash
git add services/expedition.py services/character.py services/explore.py services/dungeon.py services/items.py services/cultivation.py tests/test_expedition_run.py tests/test_expedition_doors.py tests/test_vitals.py
git commit -m "实现征途入口与稳定门生成"
```

---

### Task 3：实现战门、精英门、休整门和歧路

**Files:**
- Modify: `services/expedition.py`
- Modify: `services/combat.py` only if run buff adapter requires a narrow helper
- Modify: `services/beast.py`
- Modify: `tests/test_expedition_doors.py`

**Interfaces:**

```python
async def choose_door(user_id: int, door_index: int,
                      now: int | None = None) -> dict: ...
```

- [ ] **Step 1：写门结算和重复点击失败测试**

覆盖：`floor_settled=0` CAS；重复 token/两个 fresh token 只能结算一次；战门和精英门使用 current hp/mp 与 active beast；胜利累积奖励；战败 hp 恢复 30%；休整恢复至 max_hp 60%；歧路不战斗并改变下一层权重。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_doors.py -v`

Expected: choose_door 缺失导致 FAIL。

- [ ] **Step 3：实现楼层抢占**

事务内读取 active run 和 current_doors，校验 phase/index 后执行：

```sql
UPDATE expedition_runs SET floor_settled=1
WHERE id=? AND user_id=? AND status='active' AND floor_settled=0;
```

rowcount=0 返回 `floor_done`。

- [ ] **Step 4：实现战斗与奖励累积**

玩家 Combatant 使用 run current hp/mp；装备、技能和 active beast 使用当前配置快照。run buffs 通过局部 stat 变换施加，不写 characters。战斗结果更新 current hp/mp；奖励只 merge 到 rewards JSON，全部标记 bound。

- [ ] **Step 5：实现休整和歧路**

休整只恢复 hp 至 max_hp 60%，不恢复 mp。歧路把 `route_modifier='high_risk'` 写入 buffs metadata，仅影响下一层：elite+15、treasure+10、battle-15、adventure-5、rest-5；生成下一层后清除 modifier。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_expedition_doors.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 3**

```bash
git add services/expedition.py services/beast.py tests/test_expedition_doors.py
git commit -m "实现征途战斗与门结算"
```

---

### Task 4：实现道器碎片选择与 run 内增益

**Files:**
- Modify: `services/expedition.py`
- Create: `tests/test_expedition_buffs.py`

- [ ] **Step 1：写五种增益和三槽上限失败测试**

测试 atk+20%、hp+15%、spd+25%、技能 mp 消耗-30%、护法符；最多 3 个；重复同种转为同档绑定普通材料；宝门和精英门胜利后生成 2—3 选 1，刷新页面选项稳定。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_buffs.py -v`

Expected: shard phase 缺失导致 FAIL。

- [ ] **Step 3：实现 shard 子阶段**

宝门和精英门收益触发时把 `phase='choose_shard'` 与稳定 options 写入 current_doors，保持 `floor_settled=1`；只有 `choose_shard()` 完成后才推进下一层。

- [ ] **Step 4：实现 buff 适配**

破障符、护体光幕、速攻令在构造 player 时乘算；汲灵珠通过复制本场 skill config 或 Combatant 的 `mp_cost_factor=0.70` 生效，不修改全局 `SKILLS`；护法符由 Task 5 消费。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_expedition_buffs.py tests/test_combat.py -v`

Expected: PASS，且全局技能 MP 配置未被运行时修改。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 4**

```bash
git add services/expedition.py tests/test_expedition_buffs.py
git commit -m "实现征途道器碎片构筑"
```

---

### Task 5：实现护法符、三败强退、见好就收和最终发奖

**Files:**
- Modify: `services/expedition.py`
- Modify: `tests/test_expedition_run.py`
- Modify: `tests/test_expedition_buffs.py`

**Interfaces:**

```python
async def retire(user_id: int, forced: bool = False,
                 now: int | None = None) -> dict: ...
```

- [ ] **Step 1：写失败与退出失败测试**

覆盖：护法符首次败北恢复 50% 并用同一敌人/seed 再战；若再败，本门只累计 1 次 fail；消耗标记幂等；无护法败北恢复 30%；fail_count=3 自动 forced retire；主动退出奖励 100%，强退 70%；重复 retire 不重复发奖。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_run.py tests/test_expedition_buffs.py -k "retire or lifesaver or fail" -v`

Expected: 退出结算缺失导致 FAIL。

- [ ] **Step 3：实现护法符重战**

第一次失败且持有 lifesaver、`consumed_lifesaver=0` 时更新标记和 current_hp=50%，重建同一敌人并使用 `door_seed+1` 重战；重战胜利不增加 fail_count，重战失败增加 1。

- [ ] **Step 4：实现一次性最终发奖**

`retire()` 在事务内 CAS `status='active'→'done'`，按 multiplier 对 rewards 数量向下取整但单项原值>0 时至少发 1；全部 bound=1。把 run current hp/mp 写回 characters，锚点设 now；清空 run 内 buffs 仅通过 status done，不写永久 buff。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_expedition_run.py tests/test_expedition_buffs.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 5**

```bash
git add services/expedition.py tests/test_expedition_run.py tests/test_expedition_buffs.py
git commit -m "实现征途贪深惩罚与最终结算"
```

---

### Task 6：复用奇遇事件表实现“遇”门

**Files:**
- Modify: `services/expedition.py`
- Modify: `services/adventure.py`
- Modify: `handlers/adventure.py`
- Create: `tests/test_expedition_adventure.py`

- [ ] **Step 1：写遇门、超时和 reward sink 失败测试**

覆盖：遇门 100% 创建 source=expedition choice；不受 4h 冷却；effects 的正奖励进入 run rewards，不即时入包；hp/mp 负面作用于 run current 值；保守超时无奖励并推进下一层；已有普通 choice 时遇门返回 `choice_pending`，floor 不丢失。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_adventure.py -v`

Expected: expedition sink 缺失导致 FAIL。

- [ ] **Step 3：实现遇门会话**

`choose_door()` 调 `adventure.create_choice_conn(..., source='expedition', bypass_cooldown=True)`；context 写 run_id、floor、door index、reward_target=expedition。current_doors phase 改 adventure 并保存 choice id。

- [ ] **Step 4：实现结算回调**

`services.adventure` 在 source=expedition 时本地导入 `services.expedition.finalize_adventure_conn()`；正奖励 merge run JSON，负面 hp/mp 更新 run，chain_next 仍由 adventure 自身管理。完成或超时后生成下一层并将 floor_settled 重置 0。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_expedition_adventure.py tests/test_adventure_choices.py tests/test_adventure_effects.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 6**

```bash
git add services/expedition.py services/adventure.py handlers/adventure.py tests/test_expedition_adventure.py
git commit -m "接入征途遇门奇遇"
```

---

### Task 7：实现 `/venture` 交互与 Rich 结算

**Files:**
- Create: `handlers/expedition.py`
- Create: `tests/test_expedition_handlers.py`
- Modify: `bot/app.py`
- Modify: `handlers/common.py`
- Modify: `config/copy.py`
- Modify: `tests/test_rich_pages.py`

- [ ] **Step 1：写 handler token 和页面失败测试**

测试 private-only；start/door/shard/retire 都使用一次性 token；callback prefix 为 `exp:`；重新打开显示同一 current_doors；结算 RichPage 将最终奖励、气血法力和退出倍率放在折叠区外。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_handlers.py -v`

Expected: handler 不存在导致 FAIL。

- [ ] **Step 3：实现命令和路由**

注册 `/venture`，主菜单按钮“🧭 征途”，帮助页放入“历练斗法”。无 active 时显示最高档和令牌数；active 时按 phase 显示门、碎片或等待奇遇；每层选门前始终显示“见好就收”。

- [ ] **Step 4：实现结算展示**

主动退出标题“征途收功”，强退标题“道途受挫”；奖励倍率、所得、当前气血法力和失败次数不折叠，逐层日志折叠。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_expedition_handlers.py tests/test_rich_pages.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 7**

```bash
git add handlers/expedition.py bot/app.py handlers/common.py config/copy.py tests/test_expedition_handlers.py tests/test_rich_pages.py
git commit -m "开放征途交互入口"
```

---

### Task 8：平衡、日常负担审计与 M4A 验收

**Files:**
- Modify: `tools/balance_sim.py`
- Create: `tests/test_expedition_balance.py`
- Create: `docs/plans/v4/m4-weekly-event-audit.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1：写四档门槛和奖励价值失败测试**

每档当前 realm 入门 GEARED+有兽可推进至少 50% 层数，上一大境界满 buff+有兽不得稳定通关；征途奖励不含 stone；单令牌期望价值不超过同档一日历练收益。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_expedition_balance.py -v`

Expected: balance 接口缺失导致 FAIL。

- [ ] **Step 3：实现 balance_sim 报告**

固定策略模拟：保守优先、战斗优先、贪深三档；输出平均到达层、强退率、奖励价值和灵兽贡献。

- [ ] **Step 4：执行日常负担审计**

`m4-weekly-event-audit.md` 记录：征途无每日次数任务，令牌自然获得；单次 6—12 层预计 2—4 分钟；按每周 1—2 枚免费令估算，日均主动操作低于 1 分钟。该文件同时为 M4B 追加镇妖塔审计预留同一表格。

- [ ] **Step 5：完整验收**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 四档门槛、奖励价值、强退率和有兽交互无越线。

- [ ] **Step 6：更新指南并提交 Task 8**

```bash
git add tools/balance_sim.py tests/test_expedition_balance.py docs/plans/v4/m4-weekly-event-audit.md docs/USER_GUIDE.md
git commit -m "完成征途平衡与负担审计"
```

---

## 四、M4A 完成定义

1. 无每日次数上限，只消耗征途令，active unique 防重入。
2. 门、碎片选项和遇门会话刷新稳定，重复 callback 不重复结算。
3. run buffs 不写永久状态，退出后消失。
4. 战败、护法符、三败强退、70%/100% 奖励倍率正确。
5. 灵兽参与每层战斗，奇遇效果正确落到 run。
6. 四档门槛和奖励价值通过 balance_sim。
7. 新增每日主动操作审计低于 5 分钟。
8. 全量测试通过。
