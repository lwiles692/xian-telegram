# 道途加成中文描述实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让道途页面使用与法宝一致的中文属性描述，不再显示内部参数名。

**Architecture:** 复用 `config.items.format_bonus()` 作为统一格式化入口，并在同一标签表补齐道途属性。`handlers.dao_path` 只负责空值语义与调用共享格式化函数，不改变服务层或数值逻辑。

**Tech Stack:** Python 3、aiogram 3.x、pytest、pytest-asyncio

## Global Constraints

- 所有用户可见字符串、注释和文档字符串使用中文，并保持现有修仙语气。
- 每个模块首行保持 `from __future__ import annotations`，仅使用绝对导入。
- 修改代码后使用 `.venv` 运行完整 `python -m pytest`。
- 不修改道途数值、数据库结构或服务层行为。

---

### Task 1: 统一道途属性描述

**Files:**
- Modify: `tests/test_dao_path.py`
- Modify: `config/items.py:142-173`
- Modify: `handlers/dao_path.py:7-18`

**Interfaces:**
- Consumes: `config.items.format_bonus(bonus: dict) -> str`
- Produces: `handlers.dao_path._bonus_text(bonuses: dict) -> str` 返回道途页面所需的中文加成文本

- [x] **Step 1: 写入失败的回归测试**

```python
from handlers import dao_path as dao_path_handler


def test_dao_path_bonus_text_uses_chinese_labels():
    text = dao_path_handler._bonus_text({"seclusion_pct": 0.11, "spd_pct": 0.06})

    assert text == "闭关加成+11%、速度加成+6%"
    assert "seclusion_pct" not in text
    assert "spd_pct" not in text
```

- [x] **Step 2: 运行回归测试并确认因参数名泄露而失败**

Run: `.venv/bin/python -m pytest tests/test_dao_path.py::test_dao_path_bonus_text_uses_chinese_labels -v`

Expected: FAIL，实际文本仍为 `seclusion_pct+11%、spd_pct+6%`。

- [x] **Step 3: 补齐共享中文标签并复用法宝格式化函数**

在 `config.items.STAT_LABEL` 中增加：

```python
    "mp_pct": "法力加成",
    "crit_pct": "暴击加成",
    "spd_pct": "速度加成",
    "alchemy_pct": "丹术加成",
    "forge_pct": "炼器加成",
    "seclusion_pct": "闭关加成",
```

在 `handlers.dao_path` 导入共享函数并替换本地参数名拼接：

```python
from config.items import format_bonus


def _bonus_text(bonuses: dict) -> str:
    if not bonuses:
        return "无"
    return format_bonus(bonuses)
```

- [x] **Step 4: 运行回归测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_dao_path.py::test_dao_path_bonus_text_uses_chinese_labels -v`

Expected: PASS。

- [x] **Step 5: 运行完整测试套件**

Run: `.venv/bin/python -m pytest`

Expected: 全部测试通过，0 failures。

- [x] **Step 6: 检查改动并提交**

```bash
git diff --check
git diff -- config/items.py handlers/dao_path.py tests/test_dao_path.py
git add config/items.py handlers/dao_path.py tests/test_dao_path.py docs/superpowers/plans/2026-07-14-dao-path-bonus-labels.md
git commit -m "修正道途加成属性描述"
```
