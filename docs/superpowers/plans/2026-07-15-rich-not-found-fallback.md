# Rich Message 404 回退 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Rich 回复和主动发送遇到 aiogram `TelegramNotFound` 时降级为普通实体消息，同时保持其他异常继续抛出。

**Architecture:** 在现有 `bot.presentation.answer()` 与 `send()` 的 Rich 调用边界增加窄范围 404 捕获，不改变 `show()` 或公共内容模型。测试使用真实 aiogram 异常类型驱动失败，再以最小实现恢复通过。

**Tech Stack:** Python 3.10+、aiogram 3.29.1、pytest、pytest-asyncio

---

## 文件结构

- Modify: `tests/test_presentation.py` — 构造真实 `TelegramNotFound`，验证 Rich 回复和主动发送均转入实体回退。
- Modify: `bot/presentation.py` — 仅在 `answer()` 和 `send()` 捕获 Rich API 的 `TelegramNotFound`。

### Task 1: 增加 Rich API 404 回归测试

**Files:**
- Modify: `tests/test_presentation.py:5-17`
- Modify: `tests/test_presentation.py:137-156`

- [x] **Step 1: 写入真实 404 异常辅助函数与失败测试**

将异常导入和辅助函数补为：

```python
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.methods import SendMessage, SendRichMessage
from aiogram.types import InputRichMessage


def _not_found() -> TelegramNotFound:
    return TelegramNotFound(
        method=SendRichMessage(
            chat_id=1,
            rich_message=InputRichMessage(html="<p>占位</p>")),
        message="Not Found")
```

在能力错误测试后增加：

```python
@pytest.mark.asyncio
async def test_answer_and_send_fall_back_when_rich_method_is_not_found(
        monkeypatch, caplog):
    error = _not_found()
    page = RichPage("capability404", "<h1>能力</h1>", Text("实体回退"))
    message = FakeMessage(rich_error=error)
    bot = FakeBot(rich_error=error)
    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")

    await answer(message, page)
    await send(bot, 7, page)

    assert [kind for kind, _kwargs in message.answers] == ["rich", "regular"]
    assert [kind for kind, _kwargs in bot.sent] == ["rich", "regular"]
    assert caplog.text.count("capability404") == 2
    assert caplog.text.count("接口不支持") == 2
```

- [x] **Step 2: 运行新测试并确认按预期失败**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_presentation.py::test_answer_and_send_fall_back_when_rich_method_is_not_found -q
```

Expected: FAIL，异常为未捕获的 `aiogram.exceptions.TelegramNotFound`，且未执行普通实体回退。

### Task 2: 实现窄范围 404 回退

**Files:**
- Modify: `bot/presentation.py:17`
- Modify: `bot/presentation.py:105-139`
- Test: `tests/test_presentation.py`

- [x] **Step 1: 导入异常并在两个 Rich 发送边界处理 404**

将异常导入改为：

```python
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
```

在 `answer()` 的 `TelegramBadRequest` 分支前增加：

```python
        except TelegramNotFound:
            logger.warning("Rich 页面 %s 回复降级：接口不支持", content.page)
            content = content.fallback
```

在 `send()` 的 `TelegramBadRequest` 分支前增加：

```python
        except TelegramNotFound:
            logger.warning("Rich 页面 %s 主动发送降级：接口不支持", content.page)
            content = content.fallback
```

- [x] **Step 2: 运行新测试并确认通过**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_presentation.py::test_answer_and_send_fall_back_when_rich_method_is_not_found -q
```

Expected: `1 passed`。

- [x] **Step 3: 运行展示层测试**

Run:

```bash
.venv/bin/python -m pytest tests/test_presentation.py -q
```

Expected: 全部通过，既有未知异常继续抛出测试不变。

- [x] **Step 4: 运行完整回归与差异检查**

Run:

```bash
.venv/bin/python -m pytest
git diff --check
```

Expected: `536 passed`，`git diff --check` 无输出。

- [x] **Step 5: 提交修复**

```bash
git add bot/presentation.py tests/test_presentation.py \
  docs/superpowers/plans/2026-07-15-rich-not-found-fallback.md
git commit -m "修复 Rich Message 404 回退"
```

### Task 3: 更新 PR 并合并

**Files:**
- No source changes.

- [ ] **Step 1: 推送 PR 头分支**

```bash
git push https://github.com/lwiles692/xian-telegram.git \
  HEAD:telegram-rich-presentation
```

Expected: 推送成功，PR #86 出现新增提交。

- [ ] **Step 2: 复核 PR 状态并转为可审查**

Run:

```bash
gh pr view 86 --json state,isDraft,mergeable,reviewDecision,statusCheckRollup
gh pr ready 86
```

Expected: PR 为开放、可合并且不再是草稿；仓库无 CI 时 `statusCheckRollup` 可为空。

- [ ] **Step 3: 合并 PR**

Run:

```bash
gh pr merge 86 --squash --delete-branch
```

Expected: PR #86 状态为 `MERGED`；远端 PR 分支按 GitHub 能力删除。
