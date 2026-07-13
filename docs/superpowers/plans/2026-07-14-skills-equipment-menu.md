# 功法法宝菜单收拢 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/skills` 法宝列表收拢为每件法宝一个换装按钮和一个操作入口，并把强化、重铸、分解及本命养成移到单件法宝页。

**Architecture:** 保持现有服务与数据库接口不变，在 `handlers/skills.py` 内提取法宝状态与导航辅助函数。列表页只生成装备/卸下的一次性令牌和只读操作入口；单件页通过 `character.item_instances(user_id)` 重新读取归属和最新状态，再生成对应的一次性操作令牌。

**Tech Stack:** Python 3、aiogram 3.x、pytest、pytest-asyncio、SQLite/aiosqlite。

## Global Constraints

- 所有用户可见文字、代码注释和文档字符串使用中文，并保持现有修仙语气。
- 所有状态变更回调必须使用 `action_callback_data()` 与 `consume_action_callback()`。
- 处理器不得直接访问数据库；法宝读取继续通过 `services.character`。
- 不修改装备、本命法宝或资源消耗规则，不修改数据库结构。
- 改动代码后必须使用仓库 `.venv` 运行完整 `python -m pytest`。

---

### Task 1: 收拢法宝列表并新增单件操作页

**Files:**
- Modify: `handlers/skills.py:80-165`
- Modify: `tests/test_skills_natal_handlers.py:55-170`

**Interfaces:**
- Consumes: `character.item_instances(user_id: int) -> list[dict]`、`character.inventory(user_id: int) -> list[tuple[str, int]]`、`action_callback_data(user_id: int, action: str) -> str`。
- Produces: `_equipment_mark(inst: dict) -> str`、`render_equipment_item(user_id: int, instance_id: int) -> tuple[str, InlineKeyboardMarkup | None]`，以及只读回调格式 `skills:item:<instance_id>`。

- [x] **Step 1: 写法宝列表失败测试**

在 `tests/test_skills_natal_handlers.py` 新增测试，创建一件已装备和一件未装备法宝，断言列表只产生两种状态变更动作与两个只读操作入口：

```python
@pytest.mark.asyncio
async def test_skills_法宝列表只保留换装与单件操作入口(temp_db):
    uid = 9300
    await character.create(uid, f"菜单道友{uid}")
    equipped_id = await _造法宝(uid, "玄铁剑")
    spare_id = await _造法宝(uid, "陨星剑")
    await character.equip_instance(uid, equipped_id)

    _text, markup = await skills_handler.render_skills_category(uid, "equipment")
    datas = _datas(markup)
    token_actions = {
        row["action"]
        for data in datas
        if (row := await _取令牌(data))
    }

    assert {f"skills:item:{equipped_id}", f"skills:item:{spare_id}"} <= set(datas)
    assert token_actions == {f"eq:unequip:{equipped_id}", f"equip:{spare_id}"}
```

- [x] **Step 2: 运行列表测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_skills_natal_handlers.py::test_skills_法宝列表只保留换装与单件操作入口 -v`

Expected: FAIL，因为当前列表仍生成 `eq:enhance:*`、`eq:reforge:*`、`eq:decompose:*` 等动作，且没有 `skills:item:*`。

- [x] **Step 3: 写单件操作页失败测试**

新增测试，断言未装备法宝的操作页提供强化、重铸、分解与返回列表，且所有状态变更操作均已生成一次性令牌：

```python
@pytest.mark.asyncio
async def test_skills_单件法宝页承载养成操作(temp_db):
    uid = 9302
    await _备好元婴道友(uid)
    inst_id = await _造法宝(uid, "天魔刃")

    _text, markup = await skills_handler.render_equipment_item(uid, inst_id)
    datas = _datas(markup)
    actions = {
        row["action"]
        for data in datas
        if (row := await _取令牌(data))
    }

    assert "skills:cat:equipment" in datas
    assert actions == {
        f"eq:enhance:{inst_id}",
        f"eq:reforge:{inst_id}",
        f"eq:decompose:{inst_id}",
        f"natal:bind:{inst_id}",
    }
```

再新增不存在实例的回退测试：

```python
@pytest.mark.asyncio
async def test_skills_不存在的单件法宝页只返回列表(temp_db):
    uid = 9303
    await character.create(uid, f"寻宝道友{uid}")

    _text, markup = await skills_handler.render_equipment_item(uid, 999999)

    assert _datas(markup) == ["skills:cat:equipment"]
```

新增拍卖托管实例的只读回退测试，确保即使用户通过旧消息打开详情，也不会生成任何状态变更令牌：

```python
@pytest.mark.asyncio
async def test_skills_拍卖托管法宝操作页不提供状态变更(temp_db):
    uid = 9306
    await character.create(uid, f"寄拍道友{uid}")
    inst_id = await _造法宝(uid, "玄铁剑")
    await db.execute(
        "UPDATE item_instances SET status=? WHERE id=?",
        ("auction", inst_id))

    _text, markup = await skills_handler.render_equipment_item(uid, inst_id)

    assert _datas(markup) == ["skills:cat:equipment"]
```

- [x] **Step 4: 运行单件页测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_skills_natal_handlers.py::test_skills_单件法宝页承载养成操作 tests/test_skills_natal_handlers.py::test_skills_不存在的单件法宝页只返回列表 tests/test_skills_natal_handlers.py::test_skills_拍卖托管法宝操作页不提供状态变更 -v`

Expected: FAIL with `AttributeError`，因为 `render_equipment_item` 尚不存在。

- [x] **Step 5: 实现列表收拢与单件操作页**

在 `handlers/skills.py` 提取状态文字函数：

```python
def _equipment_mark(inst: dict) -> str:
    if inst.get("status") == auction_cfg.INSTANCE_STATUS_AUCTION:
        return "拍卖托管"
    if int(inst.get("natal_level") or 0) > 0:
        return f"本命Lv.{inst['natal_level']}"
    if int(inst.get("bound") or 0):
        return "已斩缚绑定"
    return "已装备" if inst["equipped_slot"] else "未装备"
```

将 `render_skills_category()` 中每件非托管法宝的按钮替换为固定双按钮行：

```python
action = (
    await action_callback_data(user_id, f"eq:unequip:{inst['id']}")
    if inst["equipped_slot"]
    else await action_callback_data(user_id, f"equip:{inst['id']}")
)
rows.append([
    InlineKeyboardButton(
        text=f"{'卸下' if inst['equipped_slot'] else '装备'} #{inst['id']}",
        callback_data=action),
    InlineKeyboardButton(
        text=f"操作 #{inst['id']}",
        callback_data=f"skills:item:{inst['id']}"),
])
```

新增 `render_equipment_item()`：读取角色、法宝列表与器魂，按最新状态生成强化、重铸、分解、本命按钮；找不到实例时只返回法宝列表按钮。拍卖托管实例只展示状态与属性，不生成状态变更按钮。所有按钮文字沿用现有中文用语，底部固定为：

```python
rows.append([InlineKeyboardButton(
    text="↩️ 返回法宝列表",
    callback_data="skills:cat:equipment")])
```

- [x] **Step 6: 运行 Task 1 测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_skills_natal_handlers.py -v`

Expected: PASS，且既有本命测试需改为先打开 `render_equipment_item(uid, inst_id)` 再取得认主、喂养与斩缚令牌。

- [x] **Step 7: 提交 Task 1**

```bash
git add handlers/skills.py tests/test_skills_natal_handlers.py
git commit -m "收拢法宝列表操作"
```

---

### Task 2: 接通单件页回调与上下文返回导航

**Files:**
- Modify: `handlers/skills.py:190-370`
- Modify: `tests/test_skills_natal_handlers.py`
- Modify: `tests/test_menu_unification.py:145-180`

**Interfaces:**
- Consumes: Task 1 的 `render_equipment_item(user_id, instance_id)` 与 `skills:item:<instance_id>`。
- Produces: `_equipment_back_markup(instance_id: int | None = None) -> InlineKeyboardMarkup`、`cb_skills_item(callback: CallbackQuery)`；装备/卸下结果返回 `skills:cat:equipment`，养成结果返回 `skills:item:<instance_id>`，分解成功仅返回法宝列表。

- [x] **Step 1: 写回调与返回导航失败测试**

新增只读详情回调测试：

```python
@pytest.mark.asyncio
async def test_skills_单件法宝回调打开操作页(temp_db):
    uid = 9304
    await character.create(uid, f"炼器道友{uid}")
    inst_id = await _造法宝(uid, "玄铁剑")
    callback = _Callback(uid, f"skills:item:{inst_id}")

    await skills_handler.cb_skills_item(callback)

    assert callback.message.edits
    assert "skills:cat:equipment" in _datas(callback.message.edits[-1][1])
    assert callback.answers == [(None, False)]
```

新增结果导航测试，直接使用一次性令牌调用现有处理器：

```python
@pytest.mark.asyncio
async def test_skills_养成结果返回当前法宝且分解结果返回列表(temp_db):
    uid = 9305
    await character.create(uid, f"百炼道友{uid}")
    enhance_id = await _造法宝(uid, "玄铁剑")
    enhance_data = await action_callback_data(uid, f"eq:enhance:{enhance_id}")
    enhanced = _Callback(uid, enhance_data)

    await skills_handler.cb_enhance(enhanced)

    assert f"skills:item:{enhance_id}" in _datas(enhanced.message.edits[-1][1])
    assert "skills:cat:equipment" in _datas(enhanced.message.edits[-1][1])

    decompose_id = await _造法宝(uid, "陨星剑")
    decompose_data = await action_callback_data(uid, f"eq:decompose:{decompose_id}")
    decomposed = _Callback(uid, decompose_data)

    await skills_handler.cb_decompose(decomposed)

    assert _datas(decomposed.message.edits[-1][1]) == ["skills:cat:equipment"]
```

同步更新 `tests/test_menu_unification.py`：法宝分类页断言 `skills:item:*` 存在，并断言 `eq:enhance:*` 不再出现在列表页；单件页再断言 `eq:enhance:*` 存在。

- [x] **Step 2: 运行回调测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_skills_natal_handlers.py::test_skills_单件法宝回调打开操作页 tests/test_skills_natal_handlers.py::test_skills_养成结果返回当前法宝且分解结果返回列表 tests/test_menu_unification.py::test_dense_feature_home_pages_link_to_categories_before_actions -v`

Expected: FAIL，因为详情回调与上下文返回标记尚未实现，菜单统一测试仍期待旧的列表页强化按钮。

- [x] **Step 3: 实现详情回调与返回标记**

新增返回标记辅助函数：

```python
def _equipment_back_markup(instance_id: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    if instance_id is not None:
        rows.append([InlineKeyboardButton(
            text=f"↩️ 返回法宝 #{instance_id}",
            callback_data=f"skills:item:{instance_id}")])
    rows.append([InlineKeyboardButton(
        text="↩️ 返回法宝列表",
        callback_data="skills:cat:equipment")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
```

新增详情回调：

```python
@router.callback_query(F.data.startswith("skills:item:"))
async def cb_skills_item(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    try:
        instance_id = int(callback.data.rsplit(":", 1)[1])
    except (AttributeError, ValueError):
        instance_id = 0
    text, markup = await render_equipment_item(callback.from_user.id, instance_id)
    await show(callback, text, markup)
    await callback.answer()
```

调整 `_eq_op()`：保留解析出的 `instance_id`；卸下结果与分解成功结果使用 `_equipment_back_markup()`，其他强化、重铸或失败结果使用 `_equipment_back_markup(instance_id)`。调整 `cb_natal_action()` 使用 `_equipment_back_markup(instance_id)`，调整 `cb_equip()` 使用 `_equipment_back_markup()`。

- [x] **Step 4: 运行处理器相关测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_skills_natal_handlers.py tests/test_menu_unification.py -v`

Expected: PASS。

- [x] **Step 5: 自检代码差异并运行完整测试**

Run: `git diff --check`

Expected: exit 0，无空白错误。

Run: `.venv/bin/python -m pytest`

Expected: PASS，0 failed。

- [x] **Step 6: 提交 Task 2**

```bash
git add handlers/skills.py tests/test_skills_natal_handlers.py tests/test_menu_unification.py docs/superpowers/plans/2026-07-14-skills-equipment-menu.md
git commit -m "新增法宝单件操作页"
```
