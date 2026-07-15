# V4-M0 合体开放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重置存档的前提下开放合体期、合体丹、三张历练图与天人劫，并完成溢出分流上移、28 天宽限重写和上线公告。

**Architecture:** 延续现有 len 驱动的境界推进、`tribulation_sessions` 三段状态机和 `big_fail_streak` 字段，仅增加 realm 6 配置与目标境界分流。合体丹以“残方四合一”提供确定性进度；宽限期使用一次性迁移标记重写，避免每次启动延后截止时间。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、pytest、pytest-asyncio、现有 balance_sim。

---

## 一、文件结构

- Modify: `config/realms.py` — 增加 realm 6、属性锚点、精力和闭关曲线。
- Modify: `config/shop.py` — 增加合体首买精力价格。
- Modify: `config/items.py` — 增加合体丹、残方、三图材料和 M1 图纸残页。
- Modify: `config/recipes.py` — 增加合体丹残方四合一配方。
- Modify: `config/maps.py` — 增加周天星海、阴阳鸿沟、寂灭深渊。
- Modify: `config/events.py` — 增加天人劫选项和 M2 灵兽踪迹氛围文案。
- Modify: `services/breakthrough.py` — 扩大失败保底范围并接入天人劫。
- Modify: `services/daily.py` — 炼虚圆满签到累计发放绑定合体丹残方。
- Modify: `services/explore.py` — 增加合体稀有掉落识别与无功能灵兽踪迹播报。
- Modify: `services/character.py`、`services/settle.py` — 复用顶点上移并更新宽限文案。
- Modify: `models/db.py` — 一次性重写 v4 宽限截止并落迁移标记。
- Modify: `handlers/cultivate.py`、`config/copy.py`、`handlers/help.py` — 合体突破、天人劫与公告文案。
- Modify: `tools/balance_sim.py` — 增加炼虚满 buff、合体过渡、首破周期与经济档。
- Create: `tests/test_heti_config.py`、`tests/test_heti_breakthrough.py`、`tests/test_heti_daily_aid.py`、`tests/test_heti_balance.py`。
- Modify: `tests/test_daohang.py`、`tests/test_breakthrough.py`、`tests/test_huashen_config.py`、`tests/test_balance.py`。
- Modify: `docs/USER_GUIDE.md`、`AGENTS.md`、`config/AGENTS.md`。

---

## 二、任务清单

### Task 1：锁定 v3 基线与合体配置七件套

**Files:**
- Create: `tests/test_heti_config.py`
- Modify: `config/realms.py`
- Modify: `config/shop.py`
- Modify: `tests/test_huashen_config.py`
- Modify: `tests/test_breakthrough.py`
- Modify: `AGENTS.md`
- Modify: `config/AGENTS.md`

**Interfaces:**
- Produces: `REALM_NAMES[6] == "合体期"`。
- Preserves: `next_stage()`、`is_big_breakthrough()` 继续按 `len(REALM_NAMES)` 工作。

- [ ] **Step 1：写 realm 6 失败测试**

创建 `tests/test_heti_config.py`，至少包含以下断言：

```python
from __future__ import annotations

from config import realms as R
from config import shop


def test_heti_realm_config_matches_spec_v4():
    assert len(R.REALM_NAMES) == 7
    assert R.REALM_NAMES[6] == "合体期"
    assert R.REALM_STAGES[6] == ["初期", "中期", "后期", "圆满"]
    assert R.STAMINA_CAP[6] == 320
    assert R.STAMINA_REGEN_SECONDS[6] == 121
    assert R.SECLUSION_STAGE_HOURS[6] == 960
    assert R._REALM_BASE_COST[6] == 35_000_000
    assert R.BIG_BREAKTHROUGH[6] == {
        "pill": "合体丹", "base_rate": 0.40, "tribulation": True,
    }
    assert shop.STAMINA_BUY_BASE[6] == 8000


def test_lianxu_full_becomes_heti_big_breakthrough_node():
    last = R.num_stages(5) - 1
    assert R.next_stage(5, last) == (6, 0)
    assert R.is_big_breakthrough(5, last) is True
    assert R.next_stage(6, R.num_stages(6) - 1) is None


def test_heti_stat_anchors_match_spec_v4():
    assert R.base_stats(6, 0) == {
        "hp": 255000, "mp": 20000, "atk": 18000,
        "df": 13200, "spd": 3400, "crit": 1050,
    }
    assert R.base_stats(6, 3) == {
        "hp": 560000, "mp": 44000, "atk": 40000,
        "df": 29000, "spd": 7500, "crit": 2300,
    }
```

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_config.py -v`

Expected: realm 6、合体配置或商店精力配置缺失导致 FAIL。

- [ ] **Step 3：实现合体静态配置**

在 `config/realms.py` 增加：

```python
REALM_NAMES = ["炼气期", "筑基期", "金丹期", "元婴期", "化神期", "炼虚期", "合体期"]
REALM_STAGES[6] = _SUB_STAGES
BIG_BREAKTHROUGH[6] = {"pill": "合体丹", "base_rate": 0.40, "tribulation": True}
_REALM_BASE_COST[6] = 35_000_000
_ANCHORS[6] = (
    dict(hp=255000, mp=20000, atk=18000, df=13200, spd=3400, crit=1050),
    dict(hp=560000, mp=44000, atk=40000, df=29000, spd=7500, crit=2300),
)
STAMINA_CAP[6] = 320
STAMINA_REGEN_SECONDS[6] = 121
SECLUSION_STAGE_HOURS[6] = 960
```

在 `config/shop.py` 增加 `STAMINA_BUY_BASE[6] = 8000`，并把境界索引说明更新为 `0..6`。

- [ ] **Step 4：清理顶点硬编码测试**

更新 `tests/test_huashen_config.py` 和 `tests/test_breakthrough.py`：炼虚圆满不再是顶点，原顶点断言移至合体圆满；全仓执行：

Run: `rg -n "realm.?==.?5|target_realm.?==.?5|next_stage\(5|REALM_NAMES\[5\]|range\([0-9]+\)" config services handlers tests tools`

Expected: 仅保留明确表达炼虚业务档的常量，所有“最高境界”判断改为 len 驱动。

- [ ] **Step 5：运行配置测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_heti_config.py tests/test_huashen_config.py tests/test_breakthrough.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 1**

```bash
git add config/realms.py config/shop.py tests/test_heti_config.py tests/test_huashen_config.py tests/test_breakthrough.py AGENTS.md config/AGENTS.md
git commit -m "增加合体境界配置"
```

---

### Task 2：建立合体丹、签到残方和首破来源

**Files:**
- Create: `tests/test_heti_daily_aid.py`
- Modify: `config/items.py`
- Modify: `config/recipes.py`
- Modify: `config/maps.py`
- Modify: `config/dungeons.py`
- Modify: `config/bosses.py`
- Modify: `services/daily.py`
- Modify: `handlers/daily.py`
- Modify: `config/copy.py`

**Interfaces:**
- Produces: `heti_pill` 配方，`合体丹残方×4 → 绑定合体丹×1`。
- Produces: 炼虚圆满且修为已满玩家签到时，若无合体丹且残方不足 4，获得绑定残方×1。

- [ ] **Step 1：写合体丹管线失败测试**

在 `tests/test_heti_daily_aid.py` 覆盖：

```python
@pytest.mark.asyncio
async def test_lianxu_full_checkin_accumulates_bound_heti_fragments(temp_db):
    uid = 12001
    last = R.num_stages(5) - 1
    await character.create(uid, "问合客")
    await character.set_progress(uid, 5, last, R.advance_cost(5, last))

    for day in range(4):
        res = await daily.checkin(uid, now=1000 + day * 86400)
        assert res["status"] == "ok"

    assert await character.item_qty(uid, "合体丹残方", bound=1) == 4


@pytest.mark.asyncio
async def test_heti_fragment_recipe_outputs_bound_pill(temp_db):
    uid = 12002
    await character.create(uid, "炼丹客")
    await character.set_progress(uid, 5, 0, 0)
    await character.add_item(uid, "合体丹残方", 4, bound=1)
    result = await crafting.start_job(uid, "heti_pill", now=1000)
    assert result["status"] == "started"
```

同时断言 `合体丹` 位于 `NO_TRADE`，`heti_pill.output.bound == 1`，炼虚难图和虚空神殿存在首破来源。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_daily_aid.py -v`

Expected: 新物品、配方或签到援助不存在导致 FAIL。

- [ ] **Step 3：增加物品与配方**

在 `config/items.py` 增加：

```python
"合体丹": {"name": "合体丹", "type": "pill", "sell": 1200},
"合体丹残方": {"name": "合体丹残方", "type": "material", "sell": 160},
"星海尘晶": {"name": "星海尘晶", "type": "material", "sell": 220},
"阴阳玄玉": {"name": "阴阳玄玉", "type": "material", "sell": 250},
"寂灭道痕": {"name": "寂灭道痕", "type": "material", "sell": 280},
"合体装备图纸残页": {"name": "合体装备图纸残页", "type": "material", "sell": 180},
```

把 `合体丹` 加入 `NO_TRADE`。在 `config/recipes.py` 增加默认可见的确定性配方：

```python
"heti_pill": {
    "name": "合体丹", "type": "alchemy", "realm": 5,
    "seconds": _minutes(60), "stone": 12_000,
    "materials": {"合体丹残方": 4},
    "output": {"kind": "item", "key": "合体丹", "qty": 1, "bound": 1},
    "default": True,
},
```

- [ ] **Step 4：配置首破来源与签到保底**

按以下边界配置掉落：

| 来源 | 合体丹残方 | 完整合体丹 | 说明 |
|---|---:|---:|---|
| `混沌古狱` | 1% | 0.2% | 炼虚可及，完整丹极低概率 |
| `虚空神殿` | 6% | 0% | 深层主来源 |
| 炼虚 Boss 前列包 | 总池 3 | 0 | 参与奖不发完整丹 |
| 合体易图 | 2% | 0 | 只供已突破玩家补充 |

将 `services/daily._maybe_grant_aid_conn()` 扩为支持 `max_qty`；合体援助调用使用：

```python
HE_TI_AID_ITEM = "合体丹残方"
HE_TI_REALM = 6
HE_TI_AID_MAX_FRAGMENTS = 4
```

发放条件为炼虚圆满、修为达到突破成本、无目标 realm 6 渡劫会话、无合体丹、残方总数小于 4。文案加入 `config.copy.DAILY_AID_TEXT`。

- [ ] **Step 5：运行相关测试、完整回归与首破模拟**

Run: `.venv/bin/python -m pytest tests/test_heti_daily_aid.py tests/test_lianxu_daily_aid.py tests/test_lianxu_pill.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 首枚合体丹期望 14—28 天，合体入口期望 28—42 天，全部来源 realm≤5。

- [ ] **Step 6：提交 Task 2**

```bash
git add config/items.py config/recipes.py config/maps.py config/dungeons.py config/bosses.py services/daily.py handlers/daily.py config/copy.py tests/test_heti_daily_aid.py
git commit -m "打通合体丹首破管线"
```

---

### Task 3：扩展失败保底并实现天人劫

**Files:**
- Create: `tests/test_heti_breakthrough.py`
- Modify: `config/events.py`
- Modify: `services/breakthrough.py`
- Modify: `handlers/cultivate.py`
- Modify: `tests/test_lianxu_breakthrough.py`
- Modify: `tests/test_heart_tribulation.py`

**Interfaces:**
- Produces: `TIANREN_TRIBULATION_ACTIONS`。
- Changes: `big_fail_streak` 对 target realm 5 和 6 生效，其他大突破仍不读不写。

- [ ] **Step 1：写天人劫和保底失败测试**

测试至少覆盖：缺合体丹返回 `need_pill`；成功判定后进入三段天人劫；第三段出现 `heart`；失败损失 30% 修为不跌境；连续失败成功率 40%→50%→60%；95% 封顶；成功清零；化神→炼虚不回归。

关键断言：

```python
assert breakthrough._guarantee_bonus(6, 2) == pytest.approx(0.20)
assert breakthrough._guarantee_bonus(5, 2) == pytest.approx(0.20)
assert breakthrough._guarantee_bonus(4, 9) == 0
assert cultivate._trial_copy(6) == ("天人劫", "天人交感")
```

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_breakthrough.py -v`

Expected: target realm 6 尚未分流导致 FAIL。

- [ ] **Step 3：实现通用高阶失败保底**

把 `LIANXU_TARGET_REALM` 改为：

```python
GUARANTEED_TARGET_REALMS = frozenset({5, 6})


def _guarantee_bonus(target_realm: int, fail_streak: int) -> float:
    if target_realm not in GUARANTEED_TARGET_REALMS:
        return 0.0
    return max(0, int(fail_streak or 0)) * BIG_FAIL_GUARANTEE_STEP
```

`_record_big_failure()` 与 `_clear_big_fail_streak()` 使用同一集合，字段注释改为“化神→炼虚、炼虚→合体两档共用；其他大突破不读不写”。

- [ ] **Step 4：实现天人劫三段配置和展示**

在 `config/events.py` 增加 `TIANREN_TRIBULATION_ACTIONS`，键固定为：

```python
{
    "harmony": {"label": "天人相应", "shield": 420, "heal_pct": 0.0, "item": None},
    "merge": {"label": "神魂交融", "shield": 300, "heal_pct": 0.20, "item": None},
    "pill": {"label": "服大还丹", "shield": 160, "heal_pct": 0.45, "item": "大还丹"},
    HEART_TRIBULATION_ACTION_KEY: HEART_TRIBULATION_ACTION,
}
```

`services.breakthrough._tribulation_actions(6)` 返回该表，`_trial_name(6)` 返回“天人劫”。`handlers/cultivate.py` 增加合体丹服用、天人劫成功/失败、缺丹来源提示。

- [ ] **Step 5：运行突破测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_heti_breakthrough.py tests/test_lianxu_breakthrough.py tests/test_heart_tribulation.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 3**

```bash
git add config/events.py services/breakthrough.py handlers/cultivate.py tests/test_heti_breakthrough.py tests/test_lianxu_breakthrough.py tests/test_heart_tribulation.py
git commit -m "增加合体天人劫与失败保底"
```

---

### Task 4：增加合体三图和 M1/M2 线索

**Files:**
- Modify: `config/maps.py`
- Modify: `config/events.py`
- Modify: `services/explore.py`
- Modify: `handlers/explore.py`
- Create: `tests/test_heti_balance.py`
- Modify: `tests/test_balance.py`

- [ ] **Step 1：写地图、时长、掉落和氛围播报失败测试**

测试固定以下配置：

| 地图 | 精力 | 时长 | 独占材料 |
|---|---:|---|---|
| 周天星海 | 24 | 18—22 分钟 | 星海尘晶 |
| 阴阳鸿沟 | 28 | 22—26 分钟 | 阴阳玄玉 |
| 寂灭深渊 | 32 | 26—30 分钟 | 寂灭道痕、合体丹残方 |

并断言 `混沌古狱`、`虚空神殿` 可掉 `合体装备图纸残页`，灵兽踪迹只产生文案、不产生库存或 DB 状态。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_balance.py -v`

Expected: 三图不存在导致 FAIL。

- [ ] **Step 3：实现三图初版怪物与掉落**

在 `config/maps.py` 增加 realm 6 三图；怪物属性以合体初期锚点为中心，通过 `tools.balance_sim.py` 反推，必须满足：易图普通怪可被炼虚满 buff 档磨过，中图普通怪仅低效可过，中图 Boss 和难图对炼虚满 buff 档成功率低于 5%。

在 `config.events.py` 增加纯文案列表：

```python
V4_BEAST_TRACE_TEASERS = (
    "远处山影间似有灵兽长啸，转瞬又归寂静。",
    "残阵旁留有陌生爪痕，灵机未散，却无兽影可寻。",
    "云海中掠过一道异兽虚影，尚未到收服之时。",
)
```

`services.explore` 仅在炼虚难图或虚空神殿相关结算中低概率返回 `teaser` 字段，handler 把该句放在战报末尾提示区，不写任何新业务状态。

- [ ] **Step 4：运行地图测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_heti_balance.py tests/test_balance.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 4**

```bash
git add config/maps.py config/events.py services/explore.py handlers/explore.py tests/test_heti_balance.py tests/test_balance.py
git commit -m "增加合体历练三图"
```

---

### Task 5：扩展 balance_sim 的合体验收档

**Files:**
- Modify: `tools/balance_sim.py`
- Modify: `tests/test_heti_balance.py`
- Modify: `tests/test_economy.py`

**Interfaces:**
- Produces: `LIANXU_FULL_BUFF_ATK`、`LIANXU_FULL_BUFF_SURV`、`HETI_LIANXU_GEARED`。
- Produces: `heti_progression_profile()`、`heti_first_breakthrough_profile()`、`m0_heti_economy_profiles()`。

- [ ] **Step 1：写平衡档失败测试**

断言范围：

```python
assert 35 <= B.heti_progression_profile()["ordinary"]["total_days"] <= 42
assert 21 <= B.heti_progression_profile()["high"]["total_days"] <= 28
assert 14 <= B.heti_first_breakthrough_profile()["first_pill_days"] <= 28
assert 28 <= B.heti_first_breakthrough_profile()["entry_days"] <= 42
```

炼虚满 buff 档必须包含炼虚装备、满淬炼、满道途、满飞升被动、本命 10 级；`HETI_LIANXU_GEARED` 为合体初期锚点配现役炼虚装备与功法。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_balance.py tests/test_economy.py -v`

Expected: 新 profile 和函数缺失导致 FAIL。

- [ ] **Step 3：实现 profile 与报告段**

`CONTENT_REALM` 增加三张合体图；推进模拟使用 realm 6、`SECLUSION_STAGE_HOURS[6]`、普通 18h/日与高活跃 22h/日两档。经济红线使用 `shop.first_buy_cost_per_stamina(6) * 0.75 == 300`。

- [ ] **Step 4：迭代数值直到所有门槛落区间**

Run: `.venv/bin/python -m tools.balance_sim`

Expected:

- 炼虚满 buff 档可刷合体易图普通怪。
- 至少一个炼虚满 buff 极端档可低效磨合体中图普通怪，折算收益低于易图且大于 0。
- 合体中图 Boss、合体难图对炼虚满 buff 档均低于 5%。
- 合体普通推进 5—6 周，高活跃 3—4 周。
- 三图灵石及可变现掉落折算低于 300 灵石/精力。

- [ ] **Step 5：运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 5**

```bash
git add tools/balance_sim.py tests/test_heti_balance.py tests/test_economy.py
git commit -m "增加合体平衡验收档"
```

---

### Task 6：一次性重写降档宽限并更新三处公告

**Files:**
- Modify: `models/db.py`
- Modify: `services/character.py`
- Modify: `services/settle.py`
- Modify: `config/copy.py`
- Modify: `handlers/help.py`
- Modify: `handlers/cultivate.py`
- Modify: `tests/test_daohang.py`

**Interfaces:**
- Produces: `GAME_FLAG_V4_OVERFLOW_GRACE_INITIALIZED`。
- Preserves: 同一数据库重复启动不会再次延后宽限截止。

- [ ] **Step 1：写 v4 一次性迁移失败测试**

测试流程：先创建带 v3 宽限值的旧库；首次以 v4 代码启动后断言截止被改为 `now+28天` 且写入迁移标记；第二次启动后断言值保持不变。

三处文案断言改为：

```python
assert "四期·合体开放公告" in version_notice
assert "合体溢出分流" in help_text
assert "突破合体" in notice
assert "3% 道行 / 0 飞升点" in notice
```

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_daohang.py -v`

Expected: 旧逻辑只 `INSERT OR IGNORE`，不会重写已有 v3 截止时间。

- [ ] **Step 3：实现一次性迁移标记**

在 `models/db.py` 增加：

```python
GAME_FLAG_V4_OVERFLOW_GRACE_INITIALIZED = "v4_overflow_grace_initialized"


async def _migrate_v4_overflow_grace(conn, now: int) -> None:
    cur = await conn.execute(
        "SELECT 1 FROM game_flags WHERE key=?",
        (GAME_FLAG_V4_OVERFLOW_GRACE_INITIALIZED,))
    migrated = await cur.fetchone()
    await cur.close()
    if migrated:
        return
    await conn.execute(
        "INSERT INTO game_flags(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (GAME_FLAG_OVERFLOW_DEMOTE_GRACE_UNTIL,
         str(now + OVERFLOW_DEMOTE_GRACE_SECONDS)))
    await conn.execute(
        "INSERT INTO game_flags(key,value) VALUES(?,?)",
        (GAME_FLAG_V4_OVERFLOW_GRACE_INITIALIZED, str(now)))
```

在 `init_db()` 中于旧 flag 确保后调用该迁移，并清理 `character` 的 flag cache。

- [ ] **Step 4：更新分流与公告文案**

顶点机制本身保持 len 驱动；仅更新文字为“合体圆满完整分流、炼虚圆满宽限后次顶点分流、突破合体恢复完整分流”。`config.copy.VERSION_NOTICE_TITLE` 改为“四期·合体开放公告”，`OVERFLOW_NOTICE_TITLE` 改为“合体溢出分流”。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_daohang.py tests/test_ascension.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 6**

```bash
git add models/db.py services/character.py services/settle.py config/copy.py handlers/help.py handlers/cultivate.py tests/test_daohang.py
git commit -m "重写四期溢出宽限期"
```

---

### Task 7：文档、完整验收与 M0 发布门槛

**Files:**
- Modify: `docs/USER_GUIDE.md`
- Modify: `spec-v4.md` only when implementation reveals a factual contradiction
- Create: `docs/plans/v4/m0-weekly-event-audit.md`

- [ ] **Step 1：更新玩家指南**

写明合体突破条件、合体丹残方四合一、天人劫三段、三张合体地图、宽限截止口径和 M1 尚未开放内容。

- [ ] **Step 2：记录周事件总量审计**

`m0-weekly-event-audit.md` 明确：M0 只升级既有突破、历练和签到路径，没有新增独立每日必做命令；新增主动操作目标为 0 分钟。

- [ ] **Step 3：执行完整验收**

Run: `.venv/bin/python -m pytest`

Expected: 536 项存量测试与全部 M0 新测试全绿。

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 合体门槛、推进时长、首破周期、经济红线全部落入 spec-v4 §13 M0 区间。

- [ ] **Step 4：人工核对公告三处**

核对 `render_version_notice()`、`render_help()`、出关收功文案均包含同一截止日期、降档口径和恢复条件；任一缺失不得发布。

- [ ] **Step 5：提交 Task 7**

```bash
git add docs/USER_GUIDE.md docs/plans/v4/m0-weekly-event-audit.md
git commit -m "补充合体开放指引与验收记录"
```

---

## 三、M0 完成定义

1. 炼虚圆满可消耗合体丹进入天人劫，失败不跌境，成功进入合体初期。
2. `big_fail_streak` 仅对目标 realm 5、6 生效，成功清零，最终成功率不超过 95%。
3. 合体丹首枚来源全部位于炼虚可及内容，残方四合一产物绑定且不可交易。
4. 合体三图、推进时长、经济产出和溢出分流符合 spec-v4 §13 M0。
5. v4 宽限首次部署重写为 28 天，重复启动不延后。
6. 版本公告、帮助页、收功文案三处一致。
7. `.venv/bin/python -m pytest` 与 `.venv/bin/python -m tools.balance_sim` 均通过。
