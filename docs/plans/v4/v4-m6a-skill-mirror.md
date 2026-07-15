# V4-M6A 功法双表扩建与镜像期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 幂等建立已学功法表与装备槽表，回填旧数据并让所有旧写入同步镜像新表，同时保持读取和玩家行为完全走旧表。

**Architecture:** M6A 是纯迁移发布，不开放第 4 槽和新神通。启动时先校验旧表无重复装备技能，再回填新表并执行数量/映射断言。注册角色和领悟功法在同一事务写旧表并镜像新表；读取仍使用 `character_skills`，便于安全回滚。

**Tech Stack:** Python 3、SQLite/aiosqlite、pytest、现有角色和功法服务。

---

## 一、文件结构

- Modify: `models/db.py` — 两张新表、extra_skill_slots、幂等迁移与一致性断言。
- Modify: `services/character.py` — 注册和学习双写，读取保持旧表。
- Modify: `services/breakthrough.py` — M6A 仍读取旧表，仅补迁移注释。
- Modify: `config/items.py` — 八种神通残页统一 `feature_pending=True`。
- Modify: `handlers/skills.py`、`services/character.py` — M6B 前使用返回 feature_pending 且不消耗。
- Create: `tools/skill_migration_audit.py` — 线上库计数和槽位差异审计。
- Create: `tests/test_skill_migration.py`、`tests/test_skill_mirror.py`、`tests/test_skill_feature_pending.py`。
- Modify: `tests/test_skills_natal_handlers.py`、`tests/test_db_isolation.py`。
- Create: `docs/plans/v4/m6a-release-checklist.md`。

---

## 二、迁移不变量

1. `character_learned_skills` 行数等于旧表 `(user_id,skill_key)` 去重数。
2. `character_equipped_skills` 与旧表逐行 `(user_id,slot,skill_key)` 一致。
3. 同一用户同一 skill 不得出现在多个槽；若旧库存在脏数据，迁移必须中止并输出用户和 skill，不得静默丢行。
4. M6A 期间 `get_skills()`、`get_mind_skill()`、`knows_skill()` 和突破护盾检查仍查旧表。
5. M6A 不删除、不改名、不冻结 `character_skills`。

---

## 三、任务清单

### Task 1：建立双表 schema、脏数据预检和幂等回填

**Files:**
- Modify: `models/db.py`
- Create: `tests/test_skill_migration.py`

- [ ] **Step 1：写新旧库迁移失败测试**

覆盖空库、新库、已有旧技能库、重复执行、旧表重复 skill 脏数据。测试新表列、PK、UNIQUE 和外键；M6A 不删除旧表。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_skill_migration.py -v`

Expected: 新表和迁移函数缺失导致 FAIL。

- [ ] **Step 3：增加 schema**

```sql
CREATE TABLE IF NOT EXISTS character_learned_skills (
    user_id INTEGER NOT NULL,
    skill_key TEXT NOT NULL,
    learned_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, skill_key)
);
CREATE TABLE IF NOT EXISTS character_equipped_skills (
    user_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    skill_key TEXT NOT NULL,
    PRIMARY KEY(user_id, slot),
    UNIQUE(user_id, skill_key),
    FOREIGN KEY(user_id, skill_key)
        REFERENCES character_learned_skills(user_id, skill_key)
);
```

增加 `extra_skill_slots INTEGER NOT NULL DEFAULT 0`，但本发布不读取。对已有 realm>=6 角色回填 1，炼虚及以下保持 0。

- [ ] **Step 4：实现预检与回填**

```python
async def _migrate_character_skills(conn) -> None:
    duplicates = await _legacy_skill_duplicates(conn)
    if duplicates:
        raise RuntimeError(f"旧功法表存在重复装备：{duplicates}")
    await conn.execute(
        "INSERT OR IGNORE INTO character_learned_skills(user_id,skill_key,learned_at) "
        "SELECT DISTINCT user_id,skill_key,0 FROM character_skills")
    await conn.execute(
        "INSERT OR IGNORE INTO character_equipped_skills(user_id,slot,skill_key) "
        "SELECT user_id,slot,skill_key FROM character_skills WHERE slot>=-1")
    await _assert_character_skill_mirror(conn)
```

断言失败抛异常并阻止启动；函数重复执行不增加行。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_skill_migration.py tests/test_db_isolation.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 1**

```bash
git add models/db.py tests/test_skill_migration.py tests/test_db_isolation.py
git commit -m "建立功法双表迁移"
```

---

### Task 2：注册角色和旧学习路径双写镜像

**Files:**
- Modify: `services/character.py`
- Create: `tests/test_skill_mirror.py`
- Modify: `tests/test_skills_natal_handlers.py`

- [ ] **Step 1：写双写与旧读失败测试**

覆盖新角色 starter skill/mind 同时出现在三张表；学习心法、填空槽、覆盖 slot2 后新 learned 表保留被覆盖的旧技能；新 equipped 表与旧表当前槽一致。

故意篡改新表后，M6A `get_skills()` 仍返回旧表结果，证明读取未切换。

- [ ] **Step 2：运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_skill_mirror.py -v`

Expected: 新角色和学习路径未镜像导致 FAIL。

- [ ] **Step 3：抽取镜像 helper**

```python
async def _mirror_skill_conn(conn, user_id: int, skill_key: str,
                             slot: int, learned_at: int) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO character_learned_skills(user_id,skill_key,learned_at) "
        "VALUES(?,?,?)", (user_id, skill_key, learned_at))
    await conn.execute(
        "DELETE FROM character_equipped_skills WHERE user_id=? AND slot=?",
        (user_id, slot))
    await conn.execute(
        "INSERT INTO character_equipped_skills(user_id,slot,skill_key) VALUES(?,?,?)",
        (user_id, slot, skill_key))
```

同一事务先完成旧表写，再调用 mirror；任一步失败全部回滚。

- [ ] **Step 4：接入注册和学习**

`create()` 在写 starter 两行后镜像；`learn_skill_from_pages()` 在每个 UPDATE/INSERT 分支后镜像。覆盖旧 slot 时不删除 learned 表旧 skill，只替换 equipped 行。

- [ ] **Step 5：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_skill_mirror.py tests/test_skills_natal_handlers.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 6：提交 Task 2**

```bash
git add services/character.py tests/test_skill_mirror.py tests/test_skills_natal_handlers.py
git commit -m "镜像旧功法写入新表"
```

---

### Task 3：复验八种残页的 feature_pending 行为并补齐测试

**Files:**
- Modify: `config/items.py`
- Modify: `services/character.py`
- Modify: `handlers/skills.py`
- Create: `tests/test_skill_feature_pending.py`

M4A Task 1 已预置八种残页，并在 `learn_skill_from_pages()` 中实现扣页前的通用 `feature_pending` guard。本任务以该实现为基线，负责复验八种残页、补齐回归测试和遗漏项，不得重复增加第二套 guard。

- [ ] **Step 1：写八种残页封印回归测试**

八种残页：混沌斩、噬魂火、霸体诀、天命一击、玄冰禁锢、净化心光、太虚剑意、星渊破。每种 `type='page'`、`need=3`、`feature_pending=True`。

集齐后点击领悟返回 `feature_pending`，库存数量不变，新旧技能表均无该 skill。

- [ ] **Step 2：运行 M4A 基线复验**

Run: `.venv/bin/python -m pytest tests/test_skill_feature_pending.py -v`

Expected: M4A 完整落地时 PASS；若个别残页定义、库存不变断言或 handler 状态映射缺失，则以具体失败项作为本任务的补齐范围。

- [ ] **Step 3：补齐差异并保持单一 guard**

复用 M4A 已有的消费前检查，不移动到扣页之后，也不按技能分别写分支：

```python
if item.get("feature_pending"):
    return {"status": "feature_pending", "skill": skill_key}
```

handler 文案：“此神通尚在天机封印中，待功法对决层开启后方可领悟。”

若基线复验已全部通过，本步骤只保留测试文件；若复验失败，仅修正缺失的 page 配置、通用 guard 或 handler 状态映射。

- [ ] **Step 4：运行测试和完整回归**

Run: `.venv/bin/python -m pytest tests/test_skill_feature_pending.py tests/test_skills_natal_handlers.py -v`

Expected: PASS。

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5：提交 Task 3**

```bash
git add config/items.py services/character.py handlers/skills.py tests/test_skill_feature_pending.py
git commit -m "补齐合体神通残页封印测试"
```

---

### Task 4：增加迁移审计工具和 M6A 发布检查表

**Files:**
- Create: `tools/skill_migration_audit.py`
- Create: `docs/plans/v4/m6a-release-checklist.md`
- Modify: `tests/test_skill_migration.py`

- [ ] **Step 1：写审计工具失败测试**

测试工具输出旧 distinct 数、新 learned 数、旧 equipped 数、新 equipped 数、缺失/多余槽位和重复 skill；一致时 exit 0，不一致时 exit 1。

- [ ] **Step 2：实现只读审计**

工具沿用 `tools/auction_audit.py` 的 DB 参数解析方式，只调用 `models.db` 读接口，不修复数据。输出中文，不打印用户隐私以外的必要 user_id/skill_key 差异。

- [ ] **Step 3：编写发布检查表**

检查表固定包含：部署前备份；首次启动迁移日志；审计 exit 0；注册/学习烟测；运行至少一个完整发布周期；期间每天记录四项计数；M6B 前再次审计；禁止清理旧表。

- [ ] **Step 4：运行完整验收**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

Run: `.venv/bin/python -m tools.skill_migration_audit --db data/xian.db`

Expected: 在测试/预发布库输出四项计数一致并 exit 0。

- [ ] **Step 5：提交 Task 4**

```bash
git add tools/skill_migration_audit.py tests/test_skill_migration.py docs/plans/v4/m6a-release-checklist.md
git commit -m "增加功法迁移审计流程"
```

---

## 四、M6A 完成定义

1. 新表幂等创建，旧数据完整回填，脏数据不被静默吞掉。
2. 注册与学习在同一事务双写，覆盖技能仍保留 learned 历史。
3. 所有读取和实际战斗仍走旧表，玩家行为不变。
4. 八种新残页不可消费，统一返回 feature_pending。
5. 迁移审计工具 exit 0，并连续运行至少一个发布周期。
6. 旧 `character_skills` 未删除、未冻结。
7. 全量测试通过。
