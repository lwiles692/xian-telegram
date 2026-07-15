# V4-M2 灵兽核心 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为元婴及以上玩家交付“捕捉→兽栏→喂养/升星→出战→守猎→拍卖”的完整灵兽闭环，并让灵兽参与历练、秘境和世界 Boss。

**Architecture:** 灵兽是独立实例，`characters.active_beast_id` 只引用本人 `status='idle'` 的实例；active 不占用额外 status。战斗引擎新增可选支援单位，支援不可被选中，主人行动后出手。捕捉机会不新增会话表，species key 编入一次性 callback token；守猎使用实例字段惰性结算。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、pytest、现有拍卖、通知和战斗引擎。

---

## 一、文件结构

- Create: `config/beasts.py` — 16 常见种族、4 稀有种族、捕捉率、资质、成长、守猎和贡献预算。
- Modify: `config/items.py`、`config/recipes.py`、`config/maps.py` — 缚灵索、兽粮、四档兽魂和地图出没表。
- Modify: `models/db.py` — `spirit_beasts`、`hunt_daily`、角色灵兽字段和索引。
- Create: `services/beast.py` — 捕捉、兽栏、出战、喂养、升星、放生、守猎和 support 构造。
- Modify: `services/combat.py` — `a_support`、`d_support`。
- Modify: `services/explore.py`、`services/dungeon.py`、`services/world_boss.py` — PvE 支援参战与捕捉机会。
- Modify: `services/auction.py`、`config/auction.py` — beast kind 托管、过户和恢复。
- Modify: `services/notifications.py` — 守猎到期通知。
- Create: `handlers/beast.py` — `/beast`、`beast:` callback 与挂拍确认。
- Modify: `handlers/explore.py`、`bot/app.py`、`handlers/common.py`、`config/copy.py`。
- Modify: `services/bonds.py`、`config/bonds.py` — 出师奖励绑定缚灵索×1。
- Modify: `tools/balance_sim.py` — 有兽档矩阵和贡献预算。
- Create: `tests/test_beast_schema.py`、`tests/test_beast_capture.py`、`tests/test_beast_growth.py`、`tests/test_beast_combat.py`、`tests/test_beast_hunt.py`、`tests/test_beast_auction.py`、`tests/test_beast_handlers.py`。
- Modify: `tests/test_combat.py`、`tests/test_balance.py`、`tests/test_auction.py`、`tests/test_playability_issues.py`。

---

## 二、数据与接口约定

### （一）状态机

| 状态 | 可出战 | 可喂养/升星 | 可守猎 | 可上拍 | 可放生 |
|---|---|---|---|---|---|
| `idle` 且非 active | 否 | 是 | 是 | 是 | 是 |
| `idle` 且 active | 是 | 是 | 否 | 否 | 是，事务内先清 active |
| `hunt` | 否 | 否 | 到期后可领取 | 否 | 否 |
| `auction` | 否 | 否 | 否 | 已托管 | 否 |

### （二）主要 service 接口

```python
async def kennel(user_id: int, now: int | None = None) -> dict: ...
async def capture(user_id: int, species_key: str, source: str,
                  now: int | None = None, rng=None) -> dict: ...
async def set_active(user_id: int, beast_id: int | None) -> dict: ...
async def feed(user_id: int, beast_id: int) -> dict: ...
async def advance_star(user_id: int, beast_id: int) -> dict: ...
async def release(user_id: int, beast_id: int) -> dict: ...
async def start_hunt(user_id: int, beast_id: int, hours: int,
                     now: int | None = None) -> dict: ...
async def collect_hunt(user_id: int, beast_id: int,
                       now: int | None = None) -> dict: ...
async def active_support(user_id: int, conn=None) -> Combatant | None: ...
```

---

## 三、任务清单

### Task 1：建立灵兽配置、物品与幂等 schema

**Files:**
- Create: `config/beasts.py`
- Create: `tests/test_beast_schema.py`
- Modify: `config/items.py`
- Modify: `config/recipes.py`
- Modify: `config/maps.py`
- Modify: `models/db.py`
- Modify: `services/character.py`

- [ ] **Step 1：写 schema 和配置失败测试**

测试 `spirit_beasts`、`hunt_daily` 的列和索引；连续两次 `init_db()` 不改变结构。角色列必须包含：

```text
active_beast_id INTEGER
beast_capture_streak INTEGER NOT NULL DEFAULT 0
```

测试 20 个 species key、四种 archetype、四个 tier、每档一个 rare。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_schema.py -v`

Expected: 新表、字段和配置缺失导致 FAIL。

- [ ] **Step 3：增加 schema 与 Character 字段**

在 `SCHEMA` 增加：

```sql
CREATE TABLE IF NOT EXISTS spirit_beasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    species_key TEXT NOT NULL,
    nickname TEXT,
    level INTEGER NOT NULL DEFAULT 0,
    star INTEGER NOT NULL DEFAULT 0,
    aptitude TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    hunt_end_at INTEGER,
    hunt_hours INTEGER,
    hunt_notified_at INTEGER,
    hunt_notify_attempts INTEGER NOT NULL DEFAULT 0,
    captured_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_beasts_owner ON spirit_beasts(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_beasts_hunt ON spirit_beasts(status, hunt_end_at);
CREATE TABLE IF NOT EXISTS hunt_daily (
    beast_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(beast_id, day)
);
```

使用 `_ensure_column()` 加角色字段，并在 `Character`、`_from_row()` 中暴露。

- [ ] **Step 4：增加灵兽物品与配方**

新增非绑定可交易 `缚灵索`、`兽粮`，绑定四档兽魂：`元婴兽魂`、`化神兽魂`、`炼虚兽魂`、`合体兽魂`。配方：

```python
"binding_rope": {
    "name": "缚灵索", "type": "forge", "realm": 3,
    "seconds": _minutes(20), "stone": 1200,
    "materials": {"玄铁矿": 6, "兽皮": 8, "妖丹": 2},
    "output": {"kind": "item", "key": "缚灵索", "qty": 1},
    "default": True,
},
"beast_feed": {
    "name": "兽粮", "type": "forge", "realm": 3,
    "seconds": _minutes(15), "stone": 500,
    "materials": {"兽皮": 3, "妖丹": 2},
    "output": {"kind": "item", "key": "兽粮", "qty": 2},
    "default": True,
},
```

- [ ] **Step 5：增加种族表、地图出没表和来源短码**

species key 使用不超过 20 字节的短 ASCII，避免 callback data 超长。配置必须包含下列名称：

| 档位 | 爆发 | 灼烧 | 疗愈 | 定身 | 稀有 |
|---|---|---|---|---|---|
| 元婴 | 裂风隼 | 赤尾火狐 | 灵蕴白鹿 | 镇岳石犀 | 雷瞳貔貅 |
| 化神 | 赤焰狻猊 | 幽冥火蟒 | 月华仙狐 | 玄冰玳龟 | 吞霄天狼 |
| 炼虚 | 掣电天隼 | 蚀骨魔蛛 | 青鸾 | 憾山魁牛 | 太虚孔雀 |
| 合体 | 噬金猰貐 | 烛阴幼蟒 | 九色神鹿 | 混沌玄武 | 星渊烛龙 |

地图配置增加 `beasts={"common": (...), "rare": (...), "appear_rate": 0.12, "source_key": "r3e"}`；仅元婴及以上地图配置。`source_key` 在全部地图中唯一，使用不超过 8 字节的稳定 ASCII 短码，不得使用中文地图 key 或展示名。schema 测试同时断言 species key、source key 均为 ASCII、长度合规且 source key 不重复；在上述上限下，一次性 token callback 最长不超过 60 字节。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_beast_schema.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 1**

```bash
git add config/beasts.py config/items.py config/recipes.py config/maps.py models/db.py services/character.py tests/test_beast_schema.py
git commit -m "建立灵兽配置与数据模型"
```

---

### Task 2：实现捕捉机会、兽栏上限和保底

**Files:**
- Create: `services/beast.py`
- Create: `tests/test_beast_capture.py`
- Modify: `services/explore.py`
- Modify: `handlers/explore.py`
- Modify: `handlers/common.py`

- [ ] **Step 1：写捕捉失败测试**

覆盖：胜利后 12% 触发；失败消耗缚灵索并使 streak+1；成功清零；常见基础 35%、稀有 12%、每败+8%、总率≤90%；无缚灵索拒绝；兽栏满 3 不触发；过期 token 不调用 service，因此不计保底。

遍历全部 species/source 组合生成真实一次性 callback，并按 Telegram 的 UTF-8 字节限制断言：

```python
data = await action_callback_data(
    user_id,
    f"beast:capture:{species_key}:explore-{source_key}",
)
assert len(data.encode("utf-8")) <= 64
```

并发测试使用两个不同有效 token 同时尝试第 3 个栏位，只允许一个 INSERT 成功，另一个返回 `kennel_full`。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_capture.py -v`

Expected: service 和机会返回字段缺失导致 FAIL。

- [ ] **Step 3：实现捕捉 service**

`capture()` 在一个事务中完成角色、realm、栏位数、灵索、species、streak 检查；先扣灵索再掷骰，失败更新 streak，成功插入实例并清零。资质 JSON 固定四键：`hp`、`atk`、`df`、`spd`；常见区间 0.85—1.15，稀有区间 0.95—1.25。

返回状态词：`missing`、`realm_low`、`bad_species`、`kennel_full`、`no_rope`、`escaped`、`captured`。

- [ ] **Step 4：在历练结算后生成捕捉机会**

仅 `win=True` 且地图有 beasts 配置时调用纯函数 `roll_encounter(map_cfg, rng)`。先检查兽栏未满，再按 12% 掷现身；物种按地图 common/rare 权重选择。返回：

```python
result["beast_encounter"] = {
    "species_key": species_key,
    "name": species_name(species_key),
    "rarity": species["rarity"],
    "source": f"explore:{map_cfg['beasts']['source_key']}",
}
```

handler 使用：

```python
encounter = result["beast_encounter"]
source_key = encounter["source"].removeprefix("explore:")
await action_callback_data(
    user_id,
    f"beast:capture:{encounter['species_key']}:explore-{source_key}",
)
```

service 按 `source_key` 反查地图并校验该物种确属对应出没表；拒绝按钮为普通导航，不改变 streak；token 15 分钟后自然失效。

- [ ] **Step 5：运行捕捉测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_beast_capture.py tests/test_spec_polish.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 2**

```bash
git add services/beast.py services/explore.py handlers/explore.py handlers/common.py tests/test_beast_capture.py
git commit -m "实现灵兽捕捉与递增保底"
```

---

### Task 3：实现兽栏、出战、喂养、升星与放生

**Files:**
- Modify: `services/beast.py`
- Create: `tests/test_beast_growth.py`

- [ ] **Step 1：写养成与状态机失败测试**

测试：等级上限按主人 realm 3/4/5/6 对应 20/30/40/50；喂养每级消耗 `1 + level//10` 份兽粮；每级属性+3%；0—3 星，升星消耗同档兽魂 4/8/16；每星乘算+5%；常见放生返同档兽魂 1，稀有返 4，均绑定。

测试 active 切换与 `status='hunt'/'auction'` 拒绝，active 放生时同事务清空 `active_beast_id`。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_growth.py -v`

Expected: 接口缺失导致 FAIL。

- [ ] **Step 3：实现属性推导纯函数**

```python
def derived_stats(beast: dict) -> dict:
    species = SPECIES[beast["species_key"]]
    growth = 1 + 0.03 * int(beast["level"])
    star = 1 + 0.05 * int(beast["star"])
    aptitude = json.loads(beast["aptitude"])
    return {
        key: int(species["base"][key] * growth * aptitude.get(key, 1.0) * star)
        for key in ("hp", "atk", "df", "spd")
    } | {"mp": species["base"]["mp"], "crit": species["base"]["crit"]}
```

- [ ] **Step 4：实现事务接口**

所有接口先用 `SELECT ... WHERE id=? AND owner_id=?` 锁定归属，再检查 status。升星、喂养、放生均在同一事务扣材料并更新实例；不存在部分扣费。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_beast_growth.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 3**

```bash
git add services/beast.py tests/test_beast_growth.py
git commit -m "实现灵兽养成与兽栏状态机"
```

---

### Task 4：扩展战斗引擎为可选支援单位

**Files:**
- Modify: `services/combat.py`
- Create: `tests/test_beast_combat.py`
- Modify: `tests/test_combat.py`

**Interfaces:**
- Changes: `simulate(a, d, ..., a_support=None, d_support=None)`。
- Preserves: 两个 support 都为 None 时原固定 seed 结果与日志逐字一致。

- [ ] **Step 1：写引擎兼容和支援顺序失败测试**

测试：None 路径与改动前固化快照完全一致；主人行动后支援出手；主人被定身时支援不出手；支援不可被 target；支援 mp/cooldown 独立；日志带 `🐾`；`HARD_ROUND_CAP` 不变。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_combat.py tests/test_combat.py -v`

Expected: `simulate()` 不接受 support 参数导致 FAIL。

- [ ] **Step 3：让 `_act()` 返回是否行动**

```python
def _act(..., owner: Combatant | None = None, log_prefix: str = "") -> bool:
    if actor.stunned:
        actor.stunned = False
        log.append(f"{log_prefix}❄️ {actor.name} 被定身，难以动弹。")
        return False
    ...
    return True
```

原调用不传 owner/prefix，保持旧日志。支援 heal 把 `owner` 作为治疗对象；burst/dot/stun 仍作用于敌方主人。

- [ ] **Step 4：在每个主人行动后调用支援**

仅当主人本回合实际行动且双方仍存活时调用对应 support。支援不是 turn order 成员，不参与先手排序，不被 dot、压力伤害或目标选择命中。

- [ ] **Step 5：实现 active support 构造**

`services.beast.active_support()` 读取 active id、owner、status 和 derived stats，按 archetype 赋予一个灵技；对象名使用 `🐾{显示名}`，供日志天然带前缀。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_beast_combat.py tests/test_combat.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 4**

```bash
git add services/combat.py services/beast.py tests/test_beast_combat.py tests/test_combat.py
git commit -m "扩展战斗引擎支持灵兽参战"
```

---

### Task 5：接入历练、秘境、世界 Boss 并建立有兽档矩阵

**Files:**
- Modify: `services/explore.py`
- Modify: `services/dungeon.py`
- Modify: `services/world_boss.py`
- Modify: `tools/balance_sim.py`
- Modify: `tests/test_beast_combat.py`
- Modify: `tests/test_balance.py`

- [ ] **Step 1：写三类 PvE 接入失败测试**

使用 monkeypatch 捕获 `simulate()` 参数，断言三处均传 `a_support`；无 active beast 时传 None。世界 Boss 伤害包含支援造成的伤害。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_combat.py -k pve -v`

Expected: 调用点未传 support 导致 FAIL。

- [ ] **Step 3：接入三个调用点**

历练和秘境在创建 player 后读取一次 active support，并在同一连战中复用其剩余 mp/cooldown；世界 Boss 每次挑战重新构造满状态 support。结算返回 `beast_name` 和 `beast_actions`，handler 可在战报状态区展示。

- [ ] **Step 4：增加有兽 profile**

`tools.balance_sim.py` 支持 profile：

```python
{"beast": {"tier": realm, "rarity": "common", "level_pct": 0.70,
           "star": 0, "aptitude": 1.0, "archetype": "burst"}}
```

新增元婴、化神、炼虚、合体 GEARED 有兽矩阵。

- [ ] **Step 5：校准贡献预算和存量门槛**

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 满级 3 星高资质兽 DPS≤同档 GEARED 15%；初捕常见兽约 6%—8%；疗愈兽每回合期望治疗≤主人 max_hp 3%；有兽后“刚解锁可刷”不提前超过一个小阶；无兽满 buff 档维持原结论。

- [ ] **Step 6：运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 5**

```bash
git add services/explore.py services/dungeon.py services/world_boss.py tools/balance_sim.py tests/test_beast_combat.py tests/test_balance.py
git commit -m "接入灵兽 PvE 参战与平衡档"
```

---

### Task 6：实现守猎惰性结算与通知

**Files:**
- Modify: `services/beast.py`
- Modify: `services/notifications.py`
- Create: `tests/test_beast_hunt.py`
- Modify: `tests/test_playability_issues.py`

- [ ] **Step 1：写守猎失败测试**

覆盖 4/8/12 小时；每日每兽最多 2 次；产出次线性，12h 约为 4h 的 2.2 倍；全部绑定且无灵石；未到期返回 pending；重复领取不重复发；守猎中不可出战/上拍/放生；通知成功一次、失败 5 次停止、新派遣重置字段。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_hunt.py -v`

Expected: 守猎接口缺失导致 FAIL。

- [ ] **Step 3：实现守猎派遣和领取**

派遣事务中校验 status、active、daily count，更新 `status='hunt'`、end/hour、通知字段并 UPSERT `hunt_daily`。领取随机种子使用 `f"hunt:{beast_id}:{hunt_end_at}:{hunt_hours}"`，保证重启后结果稳定；成功发绑定物品后把 status 恢复 idle 并清空 hunt 字段。

- [ ] **Step 4：扩展通知服务**

新增 `_notify_beast_hunts()`，查询 `status='hunt' AND hunt_end_at<=? AND hunt_notified_at IS NULL`；复用 `MAX_NOTIFY_ATTEMPTS=5`，但失败更新以 beast id 为主键。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_beast_hunt.py tests/test_playability_issues.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 6**

```bash
git add services/beast.py services/notifications.py tests/test_beast_hunt.py tests/test_playability_issues.py
git commit -m "实现灵兽守猎与到期提醒"
```

---

### Task 7：接入拍卖行 beast kind

**Files:**
- Modify: `config/auction.py`
- Modify: `services/auction.py`
- Create: `tests/test_beast_auction.py`
- Modify: `tests/test_auction.py`

- [ ] **Step 1：写灵兽托管、流拍和成交失败测试**

覆盖：active/hunt/auction 拒绝挂拍；idle 挂拍后 status=auction；流拍恢复 idle；成交更新 owner_id、保留 level/star/aptitude；卖家 active id 不残留；稀有兽或高价成交进入 `game_events`；重复结算不重复过户。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_auction.py -v`

Expected: `KIND_BEAST` 与 `create_beast_auction()` 缺失导致 FAIL。

- [ ] **Step 3：扩展配置和 lot 分发**

```python
KIND_BEAST = "beast"
AUCTION_KINDS = frozenset({KIND_EQUIPMENT, KIND_MATERIAL, KIND_BEAST})
BEAST_FLOOR_PRICE_BY_TIER = {"yuanying": 3000, "huashen": 12000,
                             "lianxu": 50000, "heti": 150000}
```

`_return_lot()`、`_complete_sale()`、`cancel()`、`_format_auction()` 根据 kind 分三路处理；beast 的 `item_key` 存 species key，展示名走 `beast.species_name()`。

- [ ] **Step 4：实现挂拍接口**

`create_beast_auction()` 在事务中检查归属、status、active、价格、卖家挂拍上限和挂拍费，再 CAS 更新 `status='auction'` 并插入 auctions。

- [ ] **Step 5：运行拍卖测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_beast_auction.py tests/test_auction.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 7**

```bash
git add config/auction.py services/auction.py tests/test_beast_auction.py tests/test_auction.py
git commit -m "接入灵兽拍卖托管"
```

---

### Task 8：实现 `/beast` 交互、出师衔接与 M2 验收

**Files:**
- Create: `handlers/beast.py`
- Create: `tests/test_beast_handlers.py`
- Modify: `bot/app.py`
- Modify: `handlers/common.py`
- Modify: `config/copy.py`
- Modify: `config/bonds.py`
- Modify: `services/bonds.py`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1：写 handler 与 token 失败测试**

测试 `/beast` private-only；捕捉、出战、休战、喂养、升星、放生、守猎、领取、挂拍确认全部生成一次性 token；重复点击不重复变更；callback 前缀固定 `beast:`。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_beast_handlers.py -v`

Expected: handler 不存在导致 FAIL。

- [ ] **Step 3：实现命令和页面**

`/beast` 展示兽栏 0/3、active beast、每只状态和操作按钮。挂拍命令格式：`/beast auction <灵兽ID> <起拍价> [一口价]`，先生成确认页，实际挂拍只在确认 token 消费后执行。

把 `/beast` 加入 `_COMMANDS`、router 和主菜单；帮助页放入“修行养成”。

- [ ] **Step 4：增加出师奖励**

在现有出师奖励中追加绑定 `缚灵索×1`，文案为“出师即闻兽”；不改变其他师徒奖励。

- [ ] **Step 5：执行控制预算穷举和完整验收**

固定 seed `0..999` 穷举玩家定身+定身兽组合，断言不存在目标连续无限失去行动直至 `HARD_ROUND_CAP`；战斗均能结束或按回合上限判定。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

Run: `.venv/bin/python -m tools.balance_sim`

Expected: M2 有兽档矩阵和贡献预算全部通过。

- [ ] **Step 6：更新指南并提交 Task 8**

```bash
git add handlers/beast.py bot/app.py handlers/common.py config/copy.py config/bonds.py services/bonds.py tests/test_beast_handlers.py docs/USER_GUIDE.md
git commit -m "开放灵兽养成完整入口"
```

---

## 四、M2 完成定义

1. 捕捉 token 15 分钟有效，失败递增、成功清零、兽栏并发上限均正确。
2. 等级、星级、放生回收、出战引用与三态互斥完整。
3. 支援引擎 None 路径逐字兼容，灵兽按主人行动后出手。
4. 历练、秘境、世界 Boss 均带 active beast，贡献计入结算。
5. 守猎幂等、绑定、通知重试和每日限次完整。
6. 灵兽拍卖保留实例成长数据，不产生额外灵石。
7. 有兽档矩阵、15% DPS、3% 治疗和控制无锁死全部通过。
8. 全量测试与 balance_sim 通过。
