# V4-M6B 神通对决层与全面参战 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 M6A 镜像稳定后切换到功法双表，开放合体第 4 槽和八种新神通，扩展战斗 AI，并让 PvP 与宗门战带灵兽完成四期收尾。

**Architecture:** 发布启动先复验 M6A 镜像，再写 cutover 标记；所有读写切新表，旧表只读保留。玩家通过 learned/equipped 分离管理技能，槽位顺序即 AI 优先级。战斗引擎在保持固定 seed 确定性的前提下增加条件选技和八种效果。

**Tech Stack:** Python 3、aiogram 3.x、SQLite/aiosqlite、pytest、现有 combat/pvp/sect_war/beast/RichPage。

---

## 一、文件结构

- Modify: `models/db.py` — M6B cutover 标记与启动前复验，不删除旧表。
- Modify: `services/character.py` — 新表读取、学习/装备/卸下、第 4 槽动态函数。
- Modify: `services/breakthrough.py` — 合体成功写 `extra_skill_slots=1`，装备功法读取切新表。
- Modify: `config/skills.py` — 八种神通与效果参数，移除全局 COMBAT_SLOTS 依赖。
- Modify: `config/items.py` — 八种残页解除 feature_pending，realm_min=6。
- Modify: `services/combat.py` — 条件选技、跳过日志、八种技能效果。
- Modify: `services/shop.py`、`config/shop.py`、`handlers/shop.py` — 合体丹残方兑换太虚剑意残页。
- Modify: `config/tower.py`、`config/dungeons.py`、`config/bosses.py`、`config/events.py`、`config/dungeons.py` 的征途表 — 神通来源接线。
- Modify: `services/dungeon.py`、`services/world_boss.py` — 神通残页按绑定库存发放，合体 Boss 增加参与奖。
- Modify: `handlers/skills.py` — 已学列表、槽位配置、equip/unequip token。
- Modify: `services/pvp.py`、`handlers/pvp.py` — 双方灵兽、技能摘要和战报。
- Modify: `services/sect_war.py`、`config/sect_war.py` — 进攻带兽、守卫+10%。
- Modify: `tools/balance_sim.py` — 四槽 build、PvP 控制和宗门战回归。
- Create: `tests/test_skill_cutover.py`、`tests/test_skill_loadout.py`、`tests/test_combat_ai.py`、`tests/test_heti_skills.py`、`tests/test_skill_sources.py`、`tests/test_pvp_beasts.py`、`tests/test_sect_war_beasts.py`。
- Modify: `tests/test_combat.py`、`tests/test_skills_natal_handlers.py`、`tests/test_rich_pages.py`、`tests/test_m4_flow.py`。
- Create: `docs/plans/v4/m6b-release-checklist.md`、`docs/plans/v4/m6-weekly-event-audit.md`。
- Modify: `docs/USER_GUIDE.md`。

---

## 二、八种神通实现定值

| 神通 | config type | 实现参数 |
|---|---|---|
| 混沌斩 | burst | coef 2.8，MP50，CD3 |
| 噬魂火 | dot+ | 两层 dot，每层 coef0.5、dur3，MP40，CD5 |
| 霸体诀 | shield+ | 护盾，下一次直接受击反伤10%，MP30，CD4 |
| 天命一击 | burst+ | 基础 coef2.2，暴击时本次 coef 额外×1.5，MP35，CD3 |
| 玄冰禁锢 | stun+ | 定身，并将目标所有正冷却+1，MP40，CD6 |
| 净化心光 | heal+ | 回复 max_hp20%，清除全部 dots，MP45，CD4 |
| 太虚剑意 | normal+ | coef1.0，按目标 df×0.5 计算，MP15，CD1 |
| 星渊破 | burst+ | coef2.4，目标有 support 时伤害×1.15，MP60，CD4 |

---

## 三、任务清单

### Task 1：执行 M6B 复验、切读并停止旧表写入

**Files:**
- Modify: `models/db.py`
- Modify: `services/character.py`
- Modify: `services/breakthrough.py`
- Create: `tests/test_skill_cutover.py`
- Create: `docs/plans/v4/m6b-release-checklist.md`

- [ ] **Step 1：写切换前置和旧表保留失败测试**

覆盖：镜像一致时写 cutover marker；不一致时启动失败；切换后 get_skills/get_mind/knows 查新表；旧表被故意篡改不影响读取；新学习不再写旧表；旧表仍存在。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_skill_cutover.py -v`

Expected: 读取仍走旧表导致 FAIL。

- [ ] **Step 3：增加 cutover 标记**

```python
GAME_FLAG_V4_M6B_SKILL_CUTOVER = "v4_m6b_skill_cutover"
```

首次启动先 `_assert_character_skill_mirror()`，通过后 INSERT 标记；已有标记则不再要求旧表继续镜像一致，因为 M6B 已停止旧写。

- [ ] **Step 4：切换读取和写入**

`get_skills()` 查 `character_equipped_skills slot>=0 ORDER BY slot`；mind 查 slot=-1；knows 查 learned。注册和学习只写新表；删除 M6A mirror 调用，但保留 helper 至 v4.1 供回滚版本使用。

`services.breakthrough._breakthrough_mods()` 的功法查询切 equipped 新表。

- [ ] **Step 5：编写发布检查表**

固定顺序：确认 M6A 运行满一个发布周期→备份→审计 exit0→部署 M6B→检查 cutover flag→注册/学习/装备烟测→不得回滚到 M6A 之前→旧表清理留 v4.1。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_skill_cutover.py tests/test_skill_migration.py tests/test_skill_mirror.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 1**

```bash
git add models/db.py services/character.py services/breakthrough.py tests/test_skill_cutover.py docs/plans/v4/m6b-release-checklist.md
git commit -m "切换功法双表读取"
```

---

### Task 2：实现已学/装备分离和动态第 4 槽

**Files:**
- Modify: `services/character.py`
- Modify: `handlers/skills.py`
- Create: `tests/test_skill_loadout.py`
- Modify: `tests/test_skills_natal_handlers.py`

**Interfaces:**

```python
def combat_slots_for(character: Character) -> range: ...
async def learned_skills(user_id: int) -> list[str]: ...
async def equipped_skill_slots(user_id: int) -> dict[int, str]: ...
async def equip_skill(user_id: int, skill_key: str, slot: int) -> dict: ...
async def unequip_skill(user_id: int, slot: int) -> dict: ...
```

- [ ] **Step 1：写槽位和 loadout 失败测试**

炼虚及以下 range(3)；realm6 但 extra=0 仍 3；realm6 且 extra=1 为 range(4)。只能装备已学技能；mind 只能 slot=-1；战技不能 slot=-1；同技能不能多槽；替换槽不删除旧 learned；卸下不遗忘。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_skill_loadout.py -v`

Expected: 动态槽位与接口缺失导致 FAIL。

- [ ] **Step 3：实现 `combat_slots_for()`**

```python
def combat_slots_for(character: Character) -> range:
    unlocked = character.realm >= 6 and int(character.extra_skill_slots or 0) >= 1
    return range(4 if unlocked else 3)
```

`Character` 暴露 extra_skill_slots。合体天人劫成功 UPDATE 同时设为 1；旧合体角色已由 M6A 回填。

- [ ] **Step 4：改造学习语义**

所有 page 学习先检查 realm_min，再扣页并 INSERT learned；不自动装备。返回 `status='learned'`。旧技能页同样采用新语义，避免再次覆盖槽位。

- [ ] **Step 5：实现 `/skills` 构筑页面**

首页显示心法槽和 0..N 战技槽；新增“已领悟”分类。装备和卸下按钮使用一次性 action：`eq:skill:<slot>:<skill_key>`、`eq:skill:clear:<slot>`。按钮文案和 callback 在 Rich/普通模式一致。

- [ ] **Step 6：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_skill_loadout.py tests/test_skills_natal_handlers.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 2**

```bash
git add services/character.py handlers/skills.py tests/test_skill_loadout.py tests/test_skills_natal_handlers.py
git commit -m "开放功法学习与装备分离"
```

---

### Task 3：实现条件选技、槽位优先级和跳过日志

**Files:**
- Modify: `services/combat.py`
- Create: `tests/test_combat_ai.py`
- Modify: `tests/test_combat.py`

**Interfaces:**
- Changes: `_choose_skill(actor, target, heal_target=None) -> tuple[str, list[str]]`。

- [ ] **Step 1：写 AI 条件失败测试**

覆盖 heal/heal+ 仅 hp<70%；shield/shield+ 已有 shield 时跳过；stun/stun+ 目标已 stunned 时跳过；有 dots 时净化心光越过槽位优先释放；无 dots 时按槽位正常轮转且仍受 70% 治疗条件；每个跳过原因进入 log。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_combat_ai.py -v`

Expected: 当前 `_choose_skill()` 不看目标和状态导致 FAIL。

- [ ] **Step 3：实现条件判断**

跳过文案固定：`（气血充盈，跳过）`、`（护盾尚在，跳过）`、`（目标已定身，跳过）`、`（法力不足，跳过）`、`（冷却未尽，跳过）`。未知技能继续静默忽略，普攻兜底。

若 heal_target 有 dots，先从 actor.skills 中找 `purify=True` 且可释放技能；否则严格按 slot 顺序。

- [ ] **Step 4：保证确定性**

条件扫描不得调用 rng；只有最终选中的攻击技能才消费随机数。固定 seed 重复运行结果、日志、rounds 完全一致。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_combat_ai.py tests/test_combat.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 3**

```bash
git add services/combat.py tests/test_combat_ai.py tests/test_combat.py
git commit -m "增加战斗条件选技与跳过日志"
```

---

### Task 4：实现八种合体神通效果

**Files:**
- Modify: `config/skills.py`
- Modify: `services/combat.py`
- Modify: `config/items.py`
- Create: `tests/test_heti_skills.py`

- [ ] **Step 1：写八技能逐项失败测试**

每技能至少测试 MP、CD、伤害/效果和日志；太虚剑意对高 df 目标伤害高于普攻；星渊破仅在 target support 非 None 时+15%；玄冰禁锢只增加正冷却；净化心光清 dots；霸体诀反伤只触发一次。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_heti_skills.py -v`

Expected: 技能配置和引擎分支缺失导致 FAIL。

- [ ] **Step 3：增加技能配置**

按本计划第二节定值写入 `SKILLS`，每个技能 `realm_min=6`；净化心光加 `purify=True`；星渊破加 `support_bonus=0.15`；太虚剑意加 `target_df_factor=0.5`。

- [ ] **Step 4：扩展 Combatant 临时状态**

增加 `reflect_once_pct: float=0.0`。霸体诀设置 shield 和 reflect_once_pct=0.10；下一次直接伤害无论是否被 shield 完全吸收，都按原始 incoming damage 反震并清零。

- [ ] **Step 5：实现技能分支**

- dot+ 追加两条独立 dot。
- burst+ 根据 skill flags 处理 crit_extra/support_bonus。
- stun+ 在设置 stunned 后遍历 target.cooldowns，将 value>0 的项+1。
- heal+ 治疗 heal_target 并清空 dots。
- normal+ 把 target df factor 作为 `_hit()` 局部参数，不修改 target 实例。

- [ ] **Step 6：解除残页封印**

八个 page item 设 `feature_pending=False`、`realm_min=6`、`bound_default=1`；学习 service 在扣页前检查角色境界。

- [ ] **Step 7：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_heti_skills.py tests/test_combat_ai.py tests/test_combat.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 8：提交 Task 4**

```bash
git add config/skills.py services/combat.py config/items.py tests/test_heti_skills.py
git commit -m "实现八种合体神通"
```

---

### Task 5：接通八种神通来源和残方兑换

**Files:**
- Modify: `config/tower.py`
- Modify: `config/dungeons.py`
- Modify: `config/bosses.py`
- Modify: `config/events.py`
- Modify: `config/shop.py`
- Modify: `services/shop.py`
- Modify: `handlers/shop.py`
- Create: `tests/test_skill_sources.py`

- [ ] **Step 1：写来源覆盖失败测试**

固定来源：混沌斩=塔61首通；噬魂火=禁地层宝门；霸体诀=九天玄宫深层；天命一击=噬星古鲲前列；玄冰禁锢=链式终端；净化心光=合体 Boss 参与奖；太虚剑意=合体丹残方兑换；星渊破=天外层精英门。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_skill_sources.py -v`

Expected: 来源未全部接线导致 FAIL。

- [ ] **Step 3：配置掉落和奖励**

所有来源发绑定残页；九天玄宫/征途权重低于普通材料；塔61固定首通 1 页；链式终端配置明确 event key；Boss 参与奖每次击败合体档给净化心光残页×1，前列另有天命一击残页总池。

九天玄宫结算把 `feature_pending/page` 掉落从普通 drops 中分离，使用 `bound=1` 入库；其余材料保持原绑定语义。世界 Boss 配置新增 `bound_drops` 和 `participation_bound_drops`，`_distribute()` 分别给前列和全部参与者写绑定库存，不能把神通页混入现有 `bound=0` drops。

- [ ] **Step 4：实现太虚剑意兑换**

`config.shop.SKILL_EXCHANGES`：

```python
"taixu_sword_page": {
    "name": "太虚剑意残页",
    "realm": 6,
    "cost_items": {"合体丹残方": 2},
    "output": {"item": "太虚剑意残页", "qty": 1, "bound": 1},
}
```

`shop.exchange()` 在事务内扣残方并发绑定页；handler 展示确认 token，不能直接用原始 callback 变更状态。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_skill_sources.py tests/test_tower_challenge.py tests/test_expedition_balance.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 5**

```bash
git add config/tower.py config/dungeons.py config/bosses.py config/events.py config/shop.py services/dungeon.py services/world_boss.py services/shop.py handlers/shop.py tests/test_skill_sources.py
git commit -m "接通合体神通残页来源"
```

---

### Task 6：让 PvP 双方带兽并扩展战报

**Files:**
- Modify: `services/pvp.py`
- Modify: `handlers/pvp.py`
- Create: `tests/test_pvp_beasts.py`
- Modify: `tests/test_rich_pages.py`

- [ ] **Step 1：写 PvP 支援和不消耗状态失败测试**

覆盖双方有兽/单方有兽/无兽；simulate 收到 a_support/d_support；rating 不重置；战斗后 characters hp/mp/stamina 不变；战报明确“本场不消耗气血、法力与精力”；显示双方灵兽名和槽位摘要。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_pvp_beasts.py -v`

Expected: PvP 未传 support 导致 FAIL。

- [ ] **Step 3：实现 combatant+support 构造**

`_combatant()` 改返回 `(Combatant, support, slots_summary)`；duel 调 `simulate(a,d,a_support=a_beast,d_support=d_beast, rules=PVP_COMBAT_RULES)`。

- [ ] **Step 4：扩展返回值和 RichPage**

返回 `attacker_beast/defender_beast/attacker_skills/defender_skills`。handler 在结果外层展示 build 摘要，逐回合日志保持 details。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_pvp_beasts.py tests/test_rich_pages.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 6**

```bash
git add services/pvp.py handlers/pvp.py tests/test_pvp_beasts.py tests/test_rich_pages.py
git commit -m "接入 PvP 灵兽与构筑战报"
```

---

### Task 7：让宗门战带兽并上调守卫 10%

**Files:**
- Modify: `config/sect_war.py`
- Modify: `services/sect_war.py`
- Create: `tests/test_sect_war_beasts.py`
- Modify: `tests/test_m4_flow.py`

- [ ] **Step 1：写守卫补偿和门槛失败测试**

测试所有 guard 的 hp/atk/df/spd/crit 相对 M5 基线×1.10 四舍五入；进攻传 a_support，守卫 d_support=None；化神圆满 GEARED+有兽稳定胜，金丹 GEARED+有兽仍败。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_sect_war_beasts.py -v`

Expected: 守卫未补偿、调用未传 support 导致 FAIL。

- [ ] **Step 3：实现守卫补偿和参战**

配置中直接写入调后数值并保留 spec-v4 §10.4 注释，不在运行时重复乘 1.10。capture 构造 active support 并传 a_support；守卫永远 None。

- [ ] **Step 4：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_sect_war_beasts.py tests/test_m4_flow.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 7**

```bash
git add config/sect_war.py services/sect_war.py tests/test_sect_war_beasts.py tests/test_m4_flow.py
git commit -m "接入宗门战灵兽与守卫补偿"
```

---

### Task 8：控制预算、场景 build、文档与四期收尾

**Files:**
- Modify: `tools/balance_sim.py`
- Modify: `tests/test_heti_skills.py`
- Modify: `tests/test_pvp_beasts.py`
- Create: `docs/plans/v4/m6-weekly-event-audit.md`
- Modify: `docs/USER_GUIDE.md`

- [ ] **Step 1：增加场景 build 回归**

固定 build：征途多连战使用噬魂火+净化心光；镇妖塔高 hp 使用混沌斩+天命一击；带兽 PvP 使用星渊破；高 df 宗门守卫使用太虚剑意。测试只验证相对优势，不把推荐组合硬编码为唯一解。

- [ ] **Step 2：执行 PvP 控制预算穷举**

固定 seed 0..4999，覆盖玩家定身、玄冰禁锢、定身兽和双方组合；断言没有连续控制直至 HARD_ROUND_CAP 的锁死，且相同 seed 结果一致。

- [ ] **Step 3：执行完整 balance_sim**

Run: `.venv/bin/python -m tools.balance_sim`

Expected: 灵兽 DPS/治疗预算不回归，四槽 build 未打穿镇妖塔/征途/PvP/宗门战门槛，世界 Boss 仍在 20—80 次区间。

- [ ] **Step 4：完成周事件总量收尾审计**

记录四期新增系统均无强制每日清单：征途令限频、镇妖塔首通、灵田批量操作、守猎后台、技能换装按需。估算新增每日主动操作目标仍低于 5 分钟。

- [ ] **Step 5：更新玩家指南和迁移说明**

写明第 4 槽、已学/装备分离、八神通来源、AI 条件、PvP/宗门战带兽；明确旧技能表将在 v4.1 验证后清理，本期不删。

- [ ] **Step 6：运行最终完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7：提交 Task 8**

```bash
git add tools/balance_sim.py tests/test_heti_skills.py tests/test_pvp_beasts.py docs/plans/v4/m6-weekly-event-audit.md docs/USER_GUIDE.md
git commit -m "完成四期神通对决与融合收尾"
```

---

## 四、M6B 完成定义

1. 功法读取和写入全部切新表，旧表只读保留，cutover 可审计。
2. 合体角色 4 槽，炼虚及以下 3 槽；学习和装备完全分离。
3. 条件 AI、槽位优先级和跳过原因日志正确。
4. 八种神通效果和八条来源均有测试。
5. PvP 与宗门战带兽，PvP 不消耗气血、法力、精力。
6. 控制预算、场景 build 和全部门槛 balance_sim 通过。
7. 四期新增每日主动操作目标仍低于 5 分钟。
8. 旧 `character_skills` 留至 v4.1，不在本期删除。
9. 全量测试通过。
