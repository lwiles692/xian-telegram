# 终审修复报告

## 修复范围

本次针对终审三项发现完成最小改动：

1. PvP 战报在 Rich HTML 与实体回退摘要中都明确显示“本场不消耗气血、法力与精力”。设计文档 §85 与第一批计划同步声明切磋资源例外，不查询或修改服务层战斗数值。
2. Rich 错误分类增加 `method not found`、`unknown rich_message field`、`unexpected rich_message` 及同类 `rich_message` 能力失败文案的窄范围降级；未知的 `chat not found` 仍继续抛出。
3. 空战斗日志在 Rich `<details>` 与实体回退折叠块中统一显示“斗法无可记述。”。

## TDD 记录

### RED

先补充回归测试并运行：

```text
.venv/bin/python -m pytest tests/test_presentation.py tests/test_rich_pages.py -q
```

结果为 5 项失败：三类 Rich 能力错误未降级、空日志 Rich 内容缺少占位、PvP 战报缺少资源例外说明。

### GREEN

完成最小实现后，新增与既有覆盖均通过；未知 `chat not found` 的抛出断言保持通过。

## 测试结果

覆盖测试：

```text
.venv/bin/python -m pytest tests/test_presentation.py tests/test_rich_pages.py tests/test_vitals.py -v
35 passed
```

全量回归：

```text
.venv/bin/python -m pytest -q
535 passed in 36.90s
```

## 修改文件

- `bot/presentation.py`
- `handlers/common.py`
- `handlers/pvp.py`
- `tests/test_presentation.py`
- `tests/test_rich_pages.py`
- `docs/superpowers/specs/2026-07-14-telegram-rich-presentation-design.md`
- `docs/superpowers/plans/2026-07-14-telegram-rich-presentation-phase-1.md`

## 提交

修复提交：`c37c0ac6b17688f9784f9e40c9c8cce357888bbb`（修复 Rich 战报终审问题）。

## 疑虑

暂无。Rich 能力错误仍通过窄范围文案匹配，普通消息路径的未知 Telegram 错误不会被吞掉。
