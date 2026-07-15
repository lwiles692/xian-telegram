# V4-M3 奇遇系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将旧版历练单事件升级为可扩充的奇遇底座，支持历练/秘境/签到触发、15 分钟选择会话、原子代价与负面结果、超时保守结算、链式奇遇和大机缘。

**Architecture:** `config/events.py` 统一保存新版事件定义；触发时把完整选项快照写入 `adventure_choices.state`，避免会话期间配置变化。玩家点击和定时任务均用 `UPDATE ... WHERE status='pending'` 争抢结算权。旧 `explore_runs.event_*` 列不删除，只保留部署前在途历练兼容路径。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、APScheduler、pytest、现有通知和 RichPage。

---

## 一、文件结构

- Modify: `config/events.py` — 新版 ENCOUNTERS schema、权重、冷却、事件包和校验器。
- Modify: `models/db.py` — `adventure_choices`、`adventure_chains`、角色冷却字段和索引。
- Create: `services/adventure.py` — 触发、选择结算、效果执行、链式推进和超时任务。
- Modify: `services/explore.py` — 停止新写旧事件列，结算后触发；保留旧 run 兼容。
- Modify: `services/dungeon.py`、`services/daily.py` — 结算后触发。
- Modify: `services/items.py` — 中毒状态与恢复丹交互不改，仅配合历练出发消费。
- Modify: `services/notifications.py` — 链式 ready 通知。
- Create: `handlers/adventure.py` — `adv:` 选择与链式开启 callback。
- Modify: `handlers/explore.py`、`handlers/dungeon.py`、`handlers/daily.py`、`bot/app.py`。
- Create: `tests/test_adventure_config.py`、`tests/test_adventure_choices.py`、`tests/test_adventure_effects.py`、`tests/test_adventure_chains.py`、`tests/test_adventure_handlers.py`、`tests/test_adventure_legacy.py`。
- Modify: `tests/test_services_flow.py`、`tests/test_playability_issues.py`、`tests/test_rich_pages.py`。
- Modify: `docs/USER_GUIDE.md`。

---

## 二、事件快照格式

`adventure_choices.state` 必须保存可独立结算的 JSON：

```python
{
    "seed": 123456,
    "realm": 5,
    "event": {
        "key": "abandoned_cave",
        "name": "荒废洞府",
        "rarity": "common",
        "desc": "前方隐约传来阵法波动……",
        "options": [
            {
                "key": "enter",
                "label": "循波入内",
                "conservative": False,
                "cost": {"stamina": 5},
                "prob_success": 0.7,
                "success_effects": {"items": {"灵草": [2, 5]}, "bound": 1},
                "failure_effects": {"hp_pct": -0.2},
                "success_flavor": "阵法残破，得了些灵草。",
                "failure_flavor": "阵法反噬，气血翻涌。",
                "chain_next": None,
            },
            {
                "key": "leave",
                "label": "谨慎绕行",
                "conservative": True,
                "cost": {},
                "prob_success": 1.0,
                "success_effects": {},
                "failure_effects": {},
                "success_flavor": "缘分擦肩而过。",
                "failure_flavor": "",
                "chain_next": None,
            },
        ],
    },
    "context": {"source_key": "混沌古狱", "return_to": "nav:explore"},
}
```

---

## 三、任务清单

### Task 1：迁移事件配置格式并建立校验器

**Files:**
- Modify: `config/events.py`
- Create: `tests/test_adventure_config.py`
- Create: `tests/test_adventure_legacy.py`

- [ ] **Step 1：写新版配置与旧事件映射失败测试**

测试每个事件都有 `key/name/rarity/realm_min/desc/options`；options 为 list；恰有一个 `conservative=True`；保守项 cost/effects 为空；rarity 只允许 common/rare/chain/grand；grand 权重不超过 1%。

旧 `cliff_cave` 必须保留 option key `probe/detour/rescue`，使部署前 callback token 仍能映射。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_adventure_config.py tests/test_adventure_legacy.py -v`

Expected: 旧 ENCOUNTERS 结构不符合新版 schema。

- [ ] **Step 3：实现配置校验器**

```python
ADVENTURE_COOLDOWN_SECONDS = 4 * 3600
ADVENTURE_CHOICE_TTL_SECONDS = 15 * 60
ADVENTURE_CHAIN_TTL_SECONDS = 48 * 3600
ADVENTURE_TRIGGER_RATES = {"explore": 0.08, "dungeon": 0.05, "checkin": 0.02}
ADVENTURE_RARITY_WEIGHTS = {"common": 70, "rare": 25, "chain": 4, "grand": 1}


def validate_encounters(events: dict) -> None:
    for event_key, event in events.items():
        assert event["key"] == event_key
        options = event["options"]
        conservative = [option for option in options if option.get("conservative")]
        assert len(conservative) == 1
        assert conservative[0].get("cost", {}) == {}
        assert conservative[0].get("success_effects", {}) == {}
        assert conservative[0].get("failure_effects", {}) == {}
```

模块加载后调用一次 `validate_encounters(ENCOUNTERS)`，错误配置应在启动时直接失败。

- [ ] **Step 4：迁移 `cliff_cave`**

把旧奖励倍率转换为显式 effects；保留 option key。旧在途历练仍通过 `services.explore.choose_event()` 读取 key，M3 新触发不再写 `explore_runs.event_key`。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_adventure_config.py tests/test_adventure_legacy.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 1**

```bash
git add config/events.py tests/test_adventure_config.py tests/test_adventure_legacy.py
git commit -m "迁移奇遇事件配置格式"
```

---

### Task 2：建立选择会话 schema 和触发入口

**Files:**
- Modify: `models/db.py`
- Create: `services/adventure.py`
- Create: `tests/test_adventure_choices.py`
- Modify: `services/character.py`

**Interfaces:**

```python
async def try_trigger_conn(conn, user_id: int, source: str, realm: int,
                           source_key: str, now: int, rng=None,
                           allowed_rarities: set[str] | None = None) -> dict | None: ...
async def create_choice_conn(conn, user_id: int, event_key: str, source: str,
                             realm: int, context: dict, now: int,
                             rng=None, bypass_cooldown: bool = False) -> dict: ...
async def pending_choice(user_id: int) -> dict | None: ...
```

- [ ] **Step 1：写 schema、唯一索引和冷却失败测试**

覆盖 `adventure_choices`、`adventure_chains` 所有 spec 列与索引；角色列 `last_event_at`。同时创建两个 pending choice 只允许一个成功。

触发测试：已有 pending 时不触发且不更新冷却；成功触发时立即写 `last_event_at=now`；4 小时内不再触发；征途 bypass 不读写冷却。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_adventure_choices.py -v`

Expected: 表、字段和 service 缺失导致 FAIL。

- [ ] **Step 3：增加 schema**

严格按 spec-v4 §5.6 建表和 partial unique index；`state` 字段保存完整 JSON 快照。角色字段使用 `_ensure_column(..., "last_event_at", "INTEGER")`。

- [ ] **Step 4：实现触发选择**

`try_trigger_conn()` 的顺序固定：检查 pending→检查 cooldown→掷触发骰→按 realm/rarity 过滤事件→按权重选择→写 choice→更新 last_event_at。签到调用传 `allowed_rarities={"common","rare"}`，并额外过滤 `chain_next` 与 grand。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_adventure_choices.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 2**

```bash
git add models/db.py services/adventure.py services/character.py tests/test_adventure_choices.py
git commit -m "建立奇遇选择会话与冷却"
```

---

### Task 3：把历练、秘境和签到改为结算后触发

**Files:**
- Modify: `services/explore.py`
- Modify: `services/dungeon.py`
- Modify: `services/daily.py`
- Modify: `handlers/explore.py`
- Modify: `handlers/dungeon.py`
- Modify: `handlers/daily.py`
- Create: `handlers/adventure.py`
- Modify: `bot/app.py`
- Create: `tests/test_adventure_handlers.py`
- Modify: `tests/test_adventure_legacy.py`

- [ ] **Step 1：写三来源触发和旧 run 兼容失败测试**

测试历练 8%、秘境 5%、签到 2%；事件在战斗奖励与 run 删除后存在独立 pending choice。部署前已有 `explore_runs.event_key='cliff_cave'` 的 run 仍可使用旧 `ex:event:probe` token 结算。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_adventure_handlers.py tests/test_adventure_legacy.py -v`

Expected: 新 trigger 尚未接入。

- [ ] **Step 3：停止新写旧事件列**

`services.explore.start()` 不再调用 `_roll_event()`，新 INSERT 不写 event_key/event_seed。`collect()` 仍保留：若旧 row 的 event_key 非空，则走 `_event_status()` / `choose_event()` 兼容分支。

- [ ] **Step 4：在结算事务末尾触发**

历练仅在完成结算后调用；秘境无论通关层数，只要结算完成均可掷 5%；签到在奖励落账后掷 2%。返回结果统一挂：

```python
result["adventure"] = choice_payload_or_none
```

已有 pending 时 `adventure=None`，不改变冷却。

- [ ] **Step 5：实现 prompt 和 callback**

`handlers/adventure.py` 提供 `choice_markup(user_id, choice)`，每个 option 生成 `adv:choose:<choice_id>:<index>` token。历练/秘境 RichPage 在折叠战报外增加“奇遇”小节；签到普通消息追加事件名称和描述。callback router 注册但不新增独立命令。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_adventure_handlers.py tests/test_adventure_legacy.py tests/test_rich_pages.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 3**

```bash
git add services/explore.py services/dungeon.py services/daily.py handlers/explore.py handlers/dungeon.py handlers/daily.py handlers/adventure.py bot/app.py tests/test_adventure_handlers.py tests/test_adventure_legacy.py tests/test_rich_pages.py
git commit -m "接入历练秘境签到奇遇"
```

---

### Task 4：实现原子选择结算、代价与负面结果

**Files:**
- Modify: `services/adventure.py`
- Create: `tests/test_adventure_effects.py`
- Modify: `services/explore.py`
- Modify: `services/beast.py`

**Interfaces:**

```python
async def settle_choice(user_id: int, choice_id: int, option_index: int,
                        settled_by: str = "player", now: int | None = None,
                        rng=None) -> dict: ...
```

- [ ] **Step 1：写效果和原子性失败测试**

覆盖：灵石/精力/绑定材料代价不足时不 claim、不扣部分资源；成功和失败分支；hp 损伤不低于 1；mp 损失 30%；灵石损失受 realm cap；中毒取较高值不叠加；事件战斗带 active beast；稀有兽出没返回正常捕捉 opportunity，不直接插入 beast。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_adventure_effects.py -v`

Expected: settle 接口缺失导致 FAIL。

- [ ] **Step 3：实现结算权抢占**

在单事务中读取 snapshot、校验 option、校验并扣 cost，然后执行：

```sql
UPDATE adventure_choices
SET status='settled', settled_at=?, settled_by=?
WHERE id=? AND user_id=? AND status='pending';
```

rowcount=0 返回 `already_settled`。效果执行失败抛出，使整个事务回滚到 pending 和未扣资源状态。

- [ ] **Step 4：实现效果解释器**

支持键：`stone`、`stamina`、`items`、`daohang`、`hp_pct`、`mp_pct`、`poison_next_explore`、`temporary_buff`、`battle`、`beast_encounter`。掉落默认绑定；grand 也不得奖励可直接套现的高额灵石。

中毒写入：

```python
state["next_explore_hp_pct"] = max(
    float(state.get("next_explore_hp_pct", 0.0)),
    float(effect["poison_next_explore"]),
)
```

- [ ] **Step 5：在历练出发快照前消费中毒**

`services.explore.start()` 和 `sweep()` 在计算 `start_hp` 后、写入 run 前扣 `max_hp*0.15`，最低 1，并从 debuff_json 删除该键；扣减后的 hp 写入出发快照。重复读取不再次扣。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_adventure_effects.py tests/test_vitals.py tests/test_beast_capture.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 4**

```bash
git add services/adventure.py services/explore.py services/beast.py tests/test_adventure_effects.py tests/test_vitals.py
git commit -m "实现奇遇代价与效果结算"
```

---

### Task 5：实现选择超时保守结算

**Files:**
- Modify: `services/adventure.py`
- Modify: `bot/app.py`
- Modify: `tests/test_adventure_choices.py`

- [ ] **Step 1：写玩家点击与定时任务竞争测试**

使用 `asyncio.gather()` 同时调用 player settle 和 `settle_expired_choices()`，断言只一个 status 生效、只发一次效果。保守项不扣资源、不给奖励；审计字段 settled_by 为 player 或 timeout。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_adventure_choices.py -k timeout -v`

Expected: 定时任务不存在导致 FAIL。

- [ ] **Step 3：实现超时扫描**

```python
async def settle_expired_choices(now: int | None = None, limit: int = 100) -> dict:
    rows = await db.fetchall(
        "SELECT id, user_id, conservative_option FROM adventure_choices "
        "WHERE status='pending' AND expire_at<=? ORDER BY expire_at,id LIMIT ?",
        (now, limit),
    )
    ...
```

逐条调用同一 `settle_choice(..., settled_by='timeout')`，不得另写效果逻辑。

- [ ] **Step 4：注册每分钟任务**

在 `bot/app.py` 增加 `scheduler.add_job(adventure_service.settle_expired_choices, "interval", minutes=1)`。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_adventure_choices.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 5**

```bash
git add services/adventure.py bot/app.py tests/test_adventure_choices.py
git commit -m "增加奇遇超时保守结算"
```

---

### Task 6：实现链式奇遇状态机与通知

**Files:**
- Modify: `services/adventure.py`
- Modify: `services/notifications.py`
- Modify: `handlers/adventure.py`
- Modify: `handlers/explore.py`
- Create: `tests/test_adventure_chains.py`
- Modify: `tests/test_playability_issues.py`

- [ ] **Step 1：写链式进度失败测试**

覆盖：不同 option 的 `chain_next` 走不同后续；同时最多一条 waiting/ready chain；普通 choice 可与 chain 共存；ready_at 前不可打开；已有普通 pending 时返回 `choice_pending`；最多 3 步；48h 超时清除；通知成功一次、失败 5 次；推进重置通知字段。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_adventure_chains.py -v`

Expected: chain 接口缺失导致 FAIL。

- [ ] **Step 3：实现 chain 创建与推进**

成功 option 有 `chain_next` 时，创建或更新 `adventure_chains`；state 保存累计已支付代价。每步 `ready_at` 由事件配置 `chain_delay_hours` 决定，expire_at 固定 `ready_at+48h`。

保守放弃 chain 时按累计已支付代价的 30% 返还；灵石向下取整，物品按原 bound 返还，精力通过 `grant_stamina_conn()` 返还。

链式当前步的 15 分钟选择会话若由 timeout 保守结算，必须把对应 chain 直接改为 expired 并清除后续进度，不按普通主动放弃返还 30%。

- [ ] **Step 4：实现开启入口**

`handlers.explore.render_menu()` 查询 active chain；ready 时显示一次性 `adv:chain:<chain_id>` 按钮，waiting 时只显示剩余时间。通知文案提示“发送 /explore 查看后续机缘”。

- [ ] **Step 5：扩展通知扫描**

查询 waiting 且 ready_at<=now 的 chain，先在数据库中幂等改为 ready，使通知失败时玩家仍可从 `/explore` 主动打开；再扫描 ready、expire_at>now、notified_at IS NULL 的行发送通知。成功记 notified_at；失败次数达到 5 后标记 notified_at 停止重试。到 expire_at 的 chain 由超时任务改 expired，不发奖励。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_adventure_chains.py tests/test_playability_issues.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 6**

```bash
git add services/adventure.py services/notifications.py handlers/adventure.py handlers/explore.py tests/test_adventure_chains.py tests/test_playability_issues.py
git commit -m "实现链式奇遇与到期提醒"
```

---

### Task 7：填充首批事件包并完成概率审计

**Files:**
- Modify: `config/events.py`
- Modify: `tests/test_adventure_config.py`
- Modify: `tests/test_adventure_effects.py`

- [ ] **Step 1：写事件数量与 key 清单失败测试**

首批必须包含以下 30 个 common key：

```text
abandoned_cave, herb_valley, broken_array, wounded_cultivator, spirit_spring,
old_ferryman, fox_lantern, stone_tablet, sword_mark, rain_shelter,
ruined_temple, wandering_merchant, beast_tracks, poison_mist, moon_well,
ancient_bell, lost_pouch, sealed_chest, meditation_echo, dead_tree_sprout,
river_pearl, cave_whisper, fallen_puppet, star_shard, beggar_immortal,
herb_thief, spirit_moth, hidden_path, thunder_stone, quiet_grave
```

12 个 rare：

```text
heavenly_flame, immortal_remnant, rare_beast_call, dao_fragment,
void_rift, ancient_recipe, sword_tomb, spirit_vein,
dragon_scale, mirror_trial, celestial_seed, moon_palace_shadow
```

4 个 chain head：`chain_old_map_1`、`chain_broken_sword_1`、`chain_white_deer_1`、`chain_star_letter_1`；每条另有 `_2`、`_3` 节点。3 个 grand：`grand_complete_recipe`、`grand_divine_art`、`grand_rare_beast`。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_adventure_config.py -k pack -v`

Expected: 事件数量不足导致 FAIL。

- [ ] **Step 3：填充事件内容**

每个事件至少两个 option，必须有一个保守项；四类负面结果均至少被两个事件覆盖；战斗事件按 realm 配置怪物；grand 产物绑定，稀有兽大机缘仅返回正常捕捉 opportunity。

- [ ] **Step 4：执行概率和经济审计**

固定 100000 次纯配置抽样，断言 grand≤1%、chain 约 4%、签到不出现 chain/grand。对所有灵石损失和奖励运行 realm cap 校验；无事件可损失绑定物、灵兽或实例装备。

- [ ] **Step 5：运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 7**

```bash
git add config/events.py tests/test_adventure_config.py tests/test_adventure_effects.py
git commit -m "填充四期首批奇遇事件"
```

---

### Task 8：Rich 展示、指南与 M3 完整验收

**Files:**
- Modify: `handlers/adventure.py`
- Modify: `tests/test_rich_pages.py`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1：增加奇遇结果 RichPage 测试**

长结果页首行粗体标题，核心成败和代价在折叠区外；战斗日志进入 details；动态事件名、物品名、灵兽名转义；普通实体回退语义一致。

- [ ] **Step 2：实现展示构造器**

短拒绝状态使用 str；普通选择结果使用 Text；含战斗或链式终局使用 RichPage。操作提示放末尾，已有按钮不重复写成长句。

- [ ] **Step 3：更新玩家指南**

写明触发率、4 小时冷却、15 分钟超时、保守选项、负面结果可恢复、链式 48 小时和征途“遇”门将在 M4 开放。

- [ ] **Step 4：执行完整验收**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 8**

```bash
git add handlers/adventure.py tests/test_rich_pages.py docs/USER_GUIDE.md
git commit -m "完成奇遇展示与使用指引"
```

---

## 四、M3 完成定义

1. 三来源触发率、冷却和 pending 唯一索引正确。
2. 玩家点击与超时任务只能结算一次，保守项零代价零奖励。
3. 代价、正负效果、中毒、战斗和灵兽机会全部原子结算。
4. 链式最多 3 步，可与普通选择共存，通知和 48h 超时完整。
5. 事件包 common≥30、rare≥12、chain≥4、grand≥3，grand 概率≤1%。
6. 部署前旧历练奇遇 callback 仍可完成，新历练不再写旧事件列。
7. 全量测试通过。
