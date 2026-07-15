# V4-M1 合体完整链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐九天玄宫、合体装备炼制链和噬星古鲲，使合体期具备完整的个人 PvE、群 Boss 与装备成长闭环。

**Architecture:** 沿用 `config.dungeons.DUNGEONS`、`config.bosses.WORLD_BOSSES`、现有图纸学习和实例装备管线，不新增副本或装备服务。所有新数值进入 `HETI_GEARED` profile，并反向校准三图、秘境和世界 Boss。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、pytest、现有 combat/balance_sim。

---

## 一、文件结构

- Modify: `config/items.py` — 合体装备、图纸与图纸残页消费物。
- Modify: `config/recipes.py` — 三张图纸合成与三件装备炼制。
- Modify: `config/dungeons.py` — 九天玄宫七层配置。
- Modify: `config/bosses.py` — `heti` 档噬星古鲲。
- Modify: `config/maps.py` — 补齐装备、Boss 和丹材掉落链。
- Modify: `config/auction.py` — 合体材料进入拍卖白名单与估值范围。
- Modify: `services/world_boss.py` — 仅复用新档，不改核心结算。
- Modify: `tools/balance_sim.py` — `HETI_GEARED`、九天玄宫和噬星古鲲报告。
- Create: `tests/test_heti_loop.py`。
- Modify: `tests/test_balance.py`、`tests/test_economy.py`、`tests/test_auction.py`。
- Modify: `docs/USER_GUIDE.md`。

---

## 二、任务清单

### Task 1：增加九天玄宫七层秘境

**Files:**
- Create: `tests/test_heti_loop.py`
- Modify: `config/dungeons.py`
- Modify: `tests/test_balance.py`

- [ ] **Step 1：写九天玄宫配置失败测试**

```python
from __future__ import annotations

from config.dungeons import DUNGEONS


def test_jiutian_dungeon_matches_spec_v4():
    dungeon = DUNGEONS["jiutian"]
    assert dungeon["name"] == "九天玄宫"
    assert dungeon["realm"] == 6
    assert dungeon["layers"] == 7
    assert dungeon["stamina"] == 80
    assert dungeon["entry_stone"] == 8000
    assert dungeon["daily_limit"] == 2
    assert {key for key, *_ in dungeon["drops"]} >= {
        "星海尘晶", "阴阳玄玉", "寂灭道痕", "合体丹残方", "合体装备图纸残页",
    }
```

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_loop.py -v`

Expected: `DUNGEONS["jiutian"]` 缺失导致 FAIL。

- [ ] **Step 3：实现七层配置**

新增 `jiutian`，普通怪两种、末层 Boss 一种；初版奖励范围为灵石 `5000—8200`、修为 `48_000`，掉落以合体三图材料和残方为主。不得在 M1 提前掉落征途令或 v4 神通残页；这些来源分别在 M4A 和 M6B 接入。

- [ ] **Step 4：增加秘境门槛测试**

在 `tools/balance_sim.py` 接入前先用现有 `dungeon_clear_fraction()` 写失败断言：合体初期+炼虚装备通关层数比例 40%—70%，合体圆满+合体装备稳定通关不低于 90%。

- [ ] **Step 5：运行相关测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_heti_loop.py tests/test_balance.py -v`

Expected: 本任务已加入的配置测试 PASS；尚未加入 Task 4 的数值门槛断言。

Run: `.venv/bin/python -m pytest`

Expected: Task 1 提交前全量 PASS；若门槛尚未定参，将门槛断言放到 Task 4 再提交。

- [ ] **Step 6：提交 Task 1**

```bash
git add config/dungeons.py tests/test_heti_loop.py
git commit -m "增加九天玄宫秘境"
```

---

### Task 2：建立合体装备图纸与炼制链

**Files:**
- Modify: `config/items.py`
- Modify: `config/recipes.py`
- Modify: `config/maps.py`
- Modify: `config/dungeons.py`
- Modify: `tests/test_heti_loop.py`

**Interfaces:**
- Produces: `周天星刃`、`阴阳道甲`、`寂灭玄佩` 三件合体玄阶装备。
- Produces: 三个图纸合成配方与三个装备炼制配方。

- [ ] **Step 1：写装备链失败测试**

测试固定以下映射：

```python
HETI_BLUEPRINT_RECIPES = {
    "周天星刃图纸": "forge_heti_blade",
    "阴阳道甲图纸": "forge_heti_armor",
    "寂灭玄佩图纸": "forge_heti_accessory",
}
```

三件装备的 slot 分别为 `weapon`、`armor`、`accessory`，realm gate 为 6，图纸均由 `合体装备图纸残页` 与对应合体材料炼成。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_loop.py -k equipment -v`

Expected: 新物品和配方缺失导致 FAIL。

- [ ] **Step 3：增加装备与图纸物品**

初版属性：

```python
"周天星刃": {
    "name": "周天星刃", "type": "equipment", "slot": "weapon", "tier": "玄",
    "bonus": {"atk": 1800, "crit": 90, "atk_pct": 0.025},
},
"阴阳道甲": {
    "name": "阴阳道甲", "type": "equipment", "slot": "armor", "tier": "玄",
    "bonus": {"hp": 9000, "df": 1600, "hp_pct": 0.025},
    "tribulation_shield": 480,
},
"寂灭玄佩": {
    "name": "寂灭玄佩", "type": "equipment", "slot": "accessory", "tier": "玄",
    "bonus": {"mp": 1800, "spd": 260, "df_pct": 0.02},
    "breakthrough_rate": 0.05,
},
```

增加三个 `type='recipe'` 图纸物品，分别指向三个装备配方。

- [ ] **Step 4：增加六个配方**

图纸合成消耗：残页 8/8/10，加对应合体材料与器魂；装备炼制消耗三图材料、器魂和灵石，产出沿用 equipment instance 管线。所有配方 `default=False`，图纸合成配方 `default=True`。

- [ ] **Step 5：补齐掉落来源**

- `混沌古狱`、`虚空神殿` 继续掉合体装备图纸残页。
- 九天玄宫深层掉完整图纸，权重 1%—2%。
- 合体中/难图掉残页，难图权重高于中图。
- 噬星古鲲前列包掉残页，不直接掉完整装备。

- [ ] **Step 6：运行装备链测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_heti_loop.py -k "equipment or recipe" -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 2**

```bash
git add config/items.py config/recipes.py config/maps.py config/dungeons.py tests/test_heti_loop.py
git commit -m "打通合体装备炼制链"
```

---

### Task 3：增加噬星古鲲世界 Boss 档

**Files:**
- Modify: `config/bosses.py`
- Modify: `tests/test_heti_loop.py`
- Modify: `tests/test_economy.py`

- [ ] **Step 1：写 Boss 配置失败测试**

```python
def test_heti_world_boss_tier_is_selectable():
    assert boss_key_for_realm(6) == "heti"
    boss = WORLD_BOSSES["heti"]
    assert boss["name"] == "噬星古鲲"
    assert boss["realm"] == 6
    assert boss["duration"] == 2 * 3600
    assert boss["stamina"] == 20
    assert "合体丹" not in boss["drops"]
```

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_loop.py -k boss -v`

Expected: `heti` 档缺失导致 FAIL。

- [ ] **Step 3：实现 Boss 档**

`_REALM_TIER[6] = "heti"`。初版共享血池 `3_600_000`，战斗假人 hp 使用 `300_000_000`，掉落池只含合体材料、炼虚材料、残方、图纸残页和后续灵兽材料占位；不得给参与奖完整合体丹。

- [ ] **Step 4：验证分档与经济**

测试化神参与者能产生正伤害但明显低于合体参与者；合体后期 GEARED 典型群击杀挑战次数落 20—80。掉落折算不得打穿首买精力红线。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_heti_loop.py tests/test_economy.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 3**

```bash
git add config/bosses.py tests/test_heti_loop.py tests/test_economy.py
git commit -m "增加噬星古鲲世界 Boss"
```

---

### Task 4：建立 HETI_GEARED 平衡档并回归全部合体门槛

**Files:**
- Modify: `tools/balance_sim.py`
- Modify: `tests/test_heti_loop.py`
- Modify: `tests/test_balance.py`
- Modify: `tests/test_economy.py`

**Interfaces:**
- Produces: `HETI_EQUIP_KEYS`、`HETI_GEARED`。
- Produces: `heti_daily_loop_profile()`。

- [ ] **Step 1：写合体装备档失败测试**

```python
assert B.HETI_EQUIP_KEYS == ["周天星刃", "阴阳道甲", "寂灭玄佩"]
assert B.dungeon_clear_fraction(6, 0, "jiutian", profile=B.HETI_GEARED, n=120) >= 0.40
assert B.dungeon_clear_fraction(6, 0, "jiutian", profile=B.HETI_GEARED, n=120) <= 0.70
assert B.dungeon_clear_fraction(6, 3, "jiutian", profile=B.HETI_GEARED, n=120) >= 0.90
```

同时复检三图小怪/Boss 与噬星古鲲挑战次数。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_loop.py tests/test_balance.py -v`

Expected: `HETI_GEARED` 缺失或初版数值不达标导致 FAIL。

- [ ] **Step 3：实现 profile 和报告**

```python
HETI_EQUIP_KEYS = ["周天星刃", "阴阳道甲", "寂灭玄佩"]
HETI_GEARED = {**LIANXU_GEARED, "equip": HETI_EQUIP_KEYS}
```

`CONTENT_REALM` 加 `jiutian: 6`，报告输出三图、九天玄宫和噬星古鲲。

- [ ] **Step 4：定参迭代**

Run: `.venv/bin/python -m tools.balance_sim`

Expected:

- 合体初期+炼虚装备为 M0 过渡档，不因合体装备上线而失去易图可刷结论。
- 合体初期+合体装备可推进九天玄宫 40%—70%。
- 合体圆满+合体装备稳定通关九天玄宫。
- 噬星古鲲典型击杀次数 20—80。
- 合体日常灵石/精力与可变现掉落均低于首买成本 75%。

- [ ] **Step 5：运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 4**

```bash
git add tools/balance_sim.py tests/test_heti_loop.py tests/test_balance.py tests/test_economy.py
git commit -m "校准合体完整战斗链"
```

---

### Task 5：拍卖白名单、指南与 M1 完成验收

**Files:**
- Modify: `config/auction.py`
- Modify: `tests/test_auction.py`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1：扩展材料白名单测试**

断言 `星海尘晶`、`阴阳玄玉`、`寂灭道痕` 位于 `MATERIAL_WHITELIST`，合体丹和合体丹残方不进入白名单。

- [ ] **Step 2：实现白名单和估值**

保持挂拍费 1%、成交税 10% 和高价播报阈值不变；只增加三种合体普通材料。

- [ ] **Step 3：更新玩家指南**

写明九天玄宫解锁、合体装备图纸链、噬星古鲲奖励定位和 M2 灵兽尚未开放。

- [ ] **Step 4：执行 M1 完整验收**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 九天玄宫、HETI_GEARED、噬星古鲲和经济报告全部落区间。

- [ ] **Step 5：提交 Task 5**

```bash
git add config/auction.py tests/test_auction.py docs/USER_GUIDE.md
git commit -m "完成合体期玩法闭环"
```

---

## 三、M1 完成定义

1. 合体初期可进入九天玄宫，合体圆满稳定通关。
2. 三件合体装备从残页、图纸到实例炼制全链路可用。
3. realm 6 群体可刷新噬星古鲲，击杀次数落 20—80。
4. 合体材料可按白名单进入拍卖，合体丹仍不可交易。
5. M0 过渡档与三图门槛未被合体装备打穿。
6. 全量测试和平衡模拟通过。
