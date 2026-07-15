# V4-M5 洞府与灵田 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付洞府 0—5 级升级链和 10 格灵田，支持六类种子、惰性成熟、施灵精品、一键收获、一键补种及成熟通知。

**Architecture:** 洞府等级存角色列，首次激活时一次创建 10 个 plot 行，页面只展示已解锁格。成熟只改变 plot 状态，不自动发奖励；收获时按 planted_at/slot 的稳定随机种子计算产出。普通产出绑定，施灵精品使用独立 item_key 且不绑定。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、pytest、现有 inventory/notifications/market/auction。

---

## 一、文件结构

- Create: `config/estate.py` — 洞府等级、升级成本、格数、种子、产出和经济上限。
- Modify: `config/items.py`、`config/recipes.py`、`config/maps.py`、`config/auction.py` — 种子、产物、灵液、兽粮草配方和精品白名单。
- Modify: `models/db.py` — `estate_plots` 与 `characters.estate_level`。
- Create: `services/estate.py` — 升级、种植、成熟、施灵、收获、批量操作。
- Modify: `services/beast.py` — 洞府 3 级守猎每日次数+1。
- Modify: `services/daily.py` — 洞府 4/5 级每周福利。
- Modify: `services/notifications.py` — 灵田成熟通知。
- Create: `handlers/estate.py` — `/estate`、`estate:` callback 与 Text 页面。
- Modify: `bot/app.py`、`handlers/common.py`、`config/copy.py`。
- Modify: `tools/balance_sim.py`、`tools/market_audit.py`、`tools/auction_audit.py` — 灵田价值和精品价格巡检。
- Create: `tests/test_estate_schema.py`、`tests/test_estate_upgrade.py`、`tests/test_estate_plots.py`、`tests/test_estate_notifications.py`、`tests/test_estate_handlers.py`、`tests/test_estate_balance.py`。
- Modify: `tests/test_beast_hunt.py`、`tests/test_daily_stamina_rewards.py`、`tests/test_auction.py`、`tests/test_market.py`。
- Modify: `docs/USER_GUIDE.md`。

---

## 二、初版配置定值

### （一）洞府升级

| 等级 | 格数 | 初版成本 | 附加功能 |
|---|---:|---|---|
| 0→1 | 2 | 灵石5000、玄铁矿×20 | 激活灵田 |
| 1→2 | 4 | 灵石20000、雷纹玄铁×12、妖丹×20 | 扩格 |
| 2→3 | 6 | 灵石80000、古战魂晶×12、天材地宝×8 | 守猎每日上限3次 |
| 3→4 | 8 | 灵石300000、天外残玉×12、星陨砂×12 | 每周绑定征途令×1 |
| 4→5 | 10 | 灵石1000000、星海尘晶×12、阴阳玄玉×8、寂灭道痕×4 | 每7次连续签到追加高级包 |

### （二）种子

| seed key | 周期 | 普通产出 | 精品 key |
|---|---:|---|---|
| `herb_seed` | 1天 | 灵草×2—4 | 无 |
| `lingzhi_spore` | 2天 | 灵芝×1—2 | 精品灵芝×1 |
| `fire_herb_seed` | 2天 | 元火草×1—2、赤火砂×1 | 精品元火草×1 |
| `jade_lotus_seed` | 3天 | 天玉莲×1 | 精品天玉莲×1 |
| `beast_grass_seed` | 1天 | 兽粮原料×3—5 | 无 |
| `pill_soil_seed` | 3天 | 丹母土×1 | 精品丹母土×1 |

---

## 三、任务清单

### Task 1：建立洞府配置、物品、配方与 schema

**Files:**
- Create: `config/estate.py`
- Create: `tests/test_estate_schema.py`
- Modify: `config/items.py`
- Modify: `config/recipes.py`
- Modify: `models/db.py`
- Modify: `services/character.py`

- [ ] **Step 1：写配置和 schema 失败测试**

测试等级 0..5、格数 0/2/4/6/8/10、成本表、六种种子、四种精品；`estate_plots` 全部列和 unique(user_id,slot)；角色 `estate_level` 默认 0；连续两次 init 幂等。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_estate_schema.py -v`

Expected: 配置和表缺失导致 FAIL。

- [ ] **Step 3：增加物品**

新增六种种子物品、灵液、灵芝、元火草、赤火砂、天玉莲、兽粮原料、丹母土和四种精品。种子、灵液、精品均可交易；普通产出是否绑定由收获服务决定，不加入 NO_TRADE。

- [ ] **Step 4：增加配方**

```python
"spirit_liquid": {
    "name": "灵液", "type": "forge", "realm": 4,
    "seconds": _minutes(30), "stone": 1800,
    "materials": {"天材地宝": 2, "星陨砂": 2, "妖丹": 3},
    "output": {"kind": "item", "key": "灵液", "qty": 1},
    "default": True,
},
"beast_grass_feed": {
    "name": "兽粮", "type": "forge", "realm": 3,
    "seconds": _minutes(10), "stone": 200,
    "materials": {"兽粮原料": 3},
    "output": {"kind": "item", "key": "兽粮", "qty": 2},
    "default": True,
},
```

- [ ] **Step 5：增加 schema 与 Character 字段**

按 spec-v4 §8.4 建表；`estate_level INTEGER NOT NULL DEFAULT 0` 用 `_ensure_column()`，并同步 Character。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_estate_schema.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 1**

```bash
git add config/estate.py config/items.py config/recipes.py models/db.py services/character.py tests/test_estate_schema.py
git commit -m "建立洞府灵田配置与数据模型"
```

---

### Task 2：实现洞府升级和并发幂等

**Files:**
- Create: `services/estate.py`
- Create: `tests/test_estate_upgrade.py`

**Interfaces:**

```python
async def overview(user_id: int, now: int | None = None) -> dict: ...
async def upgrade(user_id: int, expected_level: int,
                  now: int | None = None) -> dict: ...
```

- [ ] **Step 1：写升级失败测试**

覆盖任意境界可激活；资源不足零扣费；每级成本正确；上限 5；0→1 创建 slot 0..9 共 10 行；两个 fresh token 带相同 expected_level 并发时只升级一次；旧 token 返回 stale_level。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_estate_upgrade.py -v`

Expected: upgrade 接口缺失导致 FAIL。

- [ ] **Step 3：实现 expected-level 事务**

事务内读取角色；current!=expected 返回 `stale_level`；按 config 检查并扣灵石/库存；CAS：

```sql
UPDATE characters SET estate_level=estate_level+1
WHERE user_id=? AND estate_level=?;
```

0→1 时 `INSERT OR IGNORE` 10 个 plot。任何异常回滚全部消耗。

- [ ] **Step 4：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_estate_upgrade.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 2**

```bash
git add services/estate.py tests/test_estate_upgrade.py
git commit -m "实现洞府升级与并发保护"
```

---

### Task 3：实现种植、惰性成熟和稳定产出

**Files:**
- Modify: `services/estate.py`
- Create: `tests/test_estate_plots.py`
- Modify: `config/maps.py`

**Interfaces:**

```python
async def plant(user_id: int, slot: int, seed_key: str,
                now: int | None = None) -> dict: ...
async def settle_mature(user_id: int, now: int | None = None) -> dict: ...
```

- [ ] **Step 1：写种植和成熟失败测试**

覆盖未激活、未解锁格、非空格、无种子、错误 seed；记录 planted_at/mature_at/last_seed_key；新种植重置 is_mature/ling/notified/attempts；到期查看改 is_mature=1；重复查看不发奖励、不重复改变。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_estate_plots.py -k "plant or mature" -v`

Expected: plant/mature 接口缺失导致 FAIL。

- [ ] **Step 3：实现种植事务**

按 slot 顺序校验解锁和空格，扣 1 枚种子，写时间戳和重置字段。成熟时间使用 config days×86400。

- [ ] **Step 4：实现惰性成熟**

```sql
UPDATE estate_plots SET is_mature=1
WHERE user_id=? AND seed_key IS NOT NULL AND is_mature=0 AND mature_at<=?;
```

只改变状态，不发库存。

- [ ] **Step 5：增加种子来源**

低阶种子进入筑基/金丹图低概率掉落；高阶种子进入炼虚/合体中难图；链式奇遇 rare/grand 可发非绑定稀有种子。地图掉落不直接给精品。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_estate_plots.py -k "plant or mature" -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 3**

```bash
git add services/estate.py config/maps.py tests/test_estate_plots.py
git commit -m "实现灵田种植与惰性成熟"
```

---

### Task 4：实现施灵、普通/精品收获和幂等

**Files:**
- Modify: `services/estate.py`
- Modify: `tests/test_estate_plots.py`

**Interfaces:**

```python
async def infuse(user_id: int, slot: int) -> dict: ...
async def harvest(user_id: int, slot: int, now: int | None = None,
                  rng=None) -> dict: ...
```

- [ ] **Step 1：写施灵和收获失败测试**

覆盖未成熟不可施灵；不支持施灵的灵草/兽粮草拒绝；灵液不足不改状态；成功只扣一次；普通产出 bound=1；精品使用独立 key、qty=1、bound=0；重复收获返回 empty；收获清 seed/current 时间和 ling，保留 last_seed_key。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_estate_plots.py -k "infuse or harvest" -v`

Expected: 接口缺失导致 FAIL。

- [ ] **Step 3：实现稳定产出 roll**

随机源固定 `random.Random(f"estate:{user_id}:{slot}:{planted_at}:{seed_key}")`。事务内先把 plot CAS 清空，再发库存；CAS rowcount=0 返回 already_harvested，避免重复发。

- [ ] **Step 4：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_estate_plots.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 4**

```bash
git add services/estate.py tests/test_estate_plots.py
git commit -m "实现灵田施灵与收获"
```

---

### Task 5：实现一键收获和一键补种

**Files:**
- Modify: `services/estate.py`
- Modify: `tests/test_estate_plots.py`

**Interfaces:**

```python
async def harvest_all(user_id: int, now: int | None = None) -> dict: ...
async def replant_all(user_id: int, now: int | None = None) -> dict: ...
```

- [ ] **Step 1：写批量操作失败测试**

一键收获只处理已熟格，普通/精品绑定语义分别正确，重复调用不重复发。一键补种按 slot 升序处理空格和 last_seed_key；库存不足时种到可用数量并返回 `missing` 汇总，不回滚已成功格；未解锁格跳过。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_estate_plots.py -k "all" -v`

Expected: 批量接口缺失导致 FAIL。

- [ ] **Step 3：实现单事务批量结算**

不要循环调用 public `harvest()`/`plant()` 造成嵌套锁；抽出 `_harvest_plot_conn()`、`_plant_plot_conn()`，批量接口在一个 transaction 中逐格执行。

- [ ] **Step 4：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_estate_plots.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 5**

```bash
git add services/estate.py tests/test_estate_plots.py
git commit -m "增加灵田批量收种"
```

---

### Task 6：接入成熟通知和重试上限

**Files:**
- Modify: `services/notifications.py`
- Create: `tests/test_estate_notifications.py`
- Modify: `tests/test_playability_issues.py`

- [ ] **Step 1：写通知失败测试**

覆盖 mature_at 到期发送一次；多个格同一用户合并一条通知；成功后把这些格 notified_at 写同一时间；失败最多 5 次；新种植重置；未收获但已通知不重复发。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_estate_notifications.py -v`

Expected: 灵田通知扫描器缺失导致 FAIL。

- [ ] **Step 3：实现用户级合并扫描**

先查询到期未通知 plot，按 user_id 分组发送“有 N 格灵田已成熟”；成功后批量更新该用户对应 plot。失败时逐格增加 attempts，第 5 次写 notified_at 停止重试。

- [ ] **Step 4：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_estate_notifications.py tests/test_playability_issues.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 6**

```bash
git add services/notifications.py tests/test_estate_notifications.py tests/test_playability_issues.py
git commit -m "增加灵田成熟提醒"
```

---

### Task 7：接入洞府等级福利和精品交易护栏

**Files:**
- Modify: `services/beast.py`
- Modify: `services/daily.py`
- Modify: `config/auction.py`
- Modify: `tools/market_audit.py`
- Modify: `tools/auction_audit.py`
- Modify: `tests/test_beast_hunt.py`
- Modify: `tests/test_daily_stamina_rewards.py`
- Modify: `tests/test_market.py`
- Modify: `tests/test_auction.py`

- [ ] **Step 1：写等级福利失败测试**

洞府 3 级守猎 limit=3；4 级每周首次签到发绑定征途令×1；5 级在连续签到 streak%7==0 时追加绑定灵液×1、兽粮×2；同周重复签到不重复发 4 级福利。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_hunt.py tests/test_daily_stamina_rewards.py -v`

Expected: 等级福利未接入导致 FAIL。

- [ ] **Step 3：实现每周发放账本**

复用 `quest_progress`：`quest_key='estate_weekly_token'`、period=Asia/Shanghai 周标签、progress=1、claimed=1。`INSERT OR IGNORE` rowcount=1 才发征途令。

- [ ] **Step 4：扩展精品交易**

所有精品可进坊市；拍卖白名单只增加 `精品天玉莲`、`精品丹母土`。审计工具将四种精品单列价格和成交量，便于每周人工巡检。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_beast_hunt.py tests/test_daily_stamina_rewards.py tests/test_market.py tests/test_auction.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 7**

```bash
git add services/beast.py services/daily.py config/auction.py tools/market_audit.py tools/auction_audit.py tests/test_beast_hunt.py tests/test_daily_stamina_rewards.py tests/test_market.py tests/test_auction.py
git commit -m "接入洞府福利与精品交易"
```

---

### Task 8：实现 `/estate` 交互、经济模拟和 M5 验收

**Files:**
- Create: `handlers/estate.py`
- Create: `tests/test_estate_handlers.py`
- Create: `tests/test_estate_balance.py`
- Modify: `bot/app.py`
- Modify: `handlers/common.py`
- Modify: `config/copy.py`
- Modify: `tools/balance_sim.py`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1：写 handler 和一次性 token 失败测试**

测试 private-only；升级、种植、施灵、单格收获、一键收获、一键补种全部使用 `estate:` token；upgrade token 含 expected_level；页面显示空/生长中/成熟、剩余时间和已施灵。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_estate_handlers.py -v`

Expected: handler 不存在导致 FAIL。

- [ ] **Step 3：实现命令和页面**

注册 `/estate`，主菜单按钮“🏡 洞府”，帮助页放入“经营交易”。普通页面使用 aiogram Text；每行只表达一格，slot 编号作为视觉锚点。

- [ ] **Step 4：增加经济 profile**

`estate_value_profile()` 按种子周期、最大产量、灵液成本、精品市场估值计算单格价值。测试每类单格最大价值≤对应档历练一日收益 30%，且种田不成为最佳灵石/精力路线。

- [ ] **Step 5：运行完整验收**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 六种种子、精品价值、洞府 sink 和每周福利无经济越线。

- [ ] **Step 6：更新指南并提交 Task 8**

```bash
git add handlers/estate.py bot/app.py handlers/common.py config/copy.py tools/balance_sim.py tests/test_estate_handlers.py tests/test_estate_balance.py docs/USER_GUIDE.md
git commit -m "开放洞府灵田经营循环"
```

---

## 四、M5 完成定义

1. 洞府升级消耗原子、expected-level 幂等、上限 5。
2. 10 格 plot、六种种子、惰性成熟和稳定产出正确。
3. 普通绑定、精品独立 key 不绑定，重复收获不重复发。
4. 一键收获和一键补种在一个事务中完成并返回清晰结果。
5. 成熟通知成功去重、失败 5 次、新种植重置。
6. 洞府 3/4/5 级福利与已有灵兽、征途、签到系统正确衔接。
7. 精品价格进入审计，单格价值不超过日收益 30%。
8. 全量测试与 balance_sim 通过。
