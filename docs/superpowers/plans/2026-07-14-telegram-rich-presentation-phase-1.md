# Telegram 富文本展示第一批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立安全、可回退的 Telegram 混合消息展示层，并完成 `/help`、`/me`、历练、秘境和 PvP 战报的第一批迁移。

**Architecture:** 新建 `bot/presentation.py`，用 `str | Text | RichPage` 表达纯文本、普通实体和 Rich Message，统一承接回复、编辑和主动发送。handler 继续从 service 取得业务 `dict`，在本域内构造中文展示；Rich HTML 与实体回退从同一份结果数据生成，格式失败时只按窄范围规则回退。

**Tech Stack:** Python 3、aiogram 3.29+（<4）/ Bot API 10.1+、pytest、pytest-asyncio、SQLite/aiosqlite。

## Global Constraints

- aiogram 依赖范围固定为 `aiogram>=3.29,<4`。
- 使用仓库 `.venv` 安装依赖和运行测试。
- 所有用户可见文字、代码注释和文档字符串使用中文，并保持现有修仙语气。
- 不设置全局 `parse_mode`；普通实体消息必须显式使用 `parse_mode=None`。
- 动态玩家名、宗门名和外部文本只能作为 `Text` 节点或经 `html.escape()` 处理。
- 不修改 service 返回值、游戏数值、数据库结构、按钮文字、callback 数据或一次性令牌规则。
- 不使用 `unittest.mock`；测试使用 `monkeypatch` 和本地 FakeBot / FakeMessage。
- 每次代码改动提交前都必须运行完整 `.venv/bin/python -m pytest`，不能只运行相关测试。

## File Structure

- Create: `bot/presentation.py` — 消息内容模型、环境开关、HTML 转义、普通参数转换、回复/编辑/主动发送和 Rich 回退。
- Create: `tests/test_presentation.py` — 展示层纯函数与 FakeBot 传输测试。
- Create: `tests/test_rich_pages.py` — `/help`、`/me` 和三类战报的结构测试。
- Modify: `requirements.txt` — 将 aiogram 最低版本提升至 3.29。
- Modify: `.env.example` — 记录 `RICH_MESSAGES_ENABLED=true`。
- Modify: `handlers/common.py` — 复用统一 `show()`，新增共享战报构造器。
- Modify: `config/copy.py` — 将帮助命令整理为静态分组数据。
- Modify: `handlers/help.py` — 构造 Rich 帮助页和版本公告，并使用统一 `answer()`。
- Modify: `handlers/me.py` — 构造分区明确的 `Text` 面板，并使用统一 `answer()`。
- Modify: `handlers/explore.py`、`handlers/dungeon.py`、`handlers/pvp.py` — 仅把成功结算迁移为 Rich 战报；短状态仍返回字符串。
- Modify: `tests/test_daohang.py`、`tests/test_playability_issues.py`、`tests/test_vitals.py`、`tests/test_bonds_handlers.py` — 使用 `plain_text()` 读取迁移后的语义文本。

---

### Task 1: 升级依赖并建立消息内容模型

**Files:**
- Create: `bot/presentation.py`
- Create: `tests/test_presentation.py`
- Modify: `requirements.txt:1`
- Modify: `.env.example`

**Interfaces:**
- Produces: `RichPage(page: str, rich_html: str, fallback: Text)`。
- Produces: `MessageContent = str | Text | RichPage`。
- Produces: `rich_messages_enabled() -> bool`、`escape_rich_html(value: object) -> str`、`plain_text(content: MessageContent) -> str`、`regular_kwargs(content: str | Text) -> dict`。
- Consumes: `aiogram.utils.formatting.Text` and `Text.as_kwargs()`。

- [ ] **Step 1: 写内容模型失败测试**

创建 `tests/test_presentation.py`：

```python
from __future__ import annotations

from aiogram.utils.formatting import Bold, Text

from bot.presentation import (RichPage, escape_rich_html, plain_text,
                              regular_kwargs, rich_messages_enabled)


def test_rich_messages_enabled_parses_only_documented_true_values(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("RICH_MESSAGES_ENABLED", value)
        assert rich_messages_enabled() is True
    for value in ("0", "false", "off", "unexpected"):
        monkeypatch.setenv("RICH_MESSAGES_ENABLED", value)
        assert rich_messages_enabled() is False
    monkeypatch.delenv("RICH_MESSAGES_ENABLED", raising=False)
    assert rich_messages_enabled() is True


def test_content_model_preserves_plain_text_and_entities():
    formatted = Text(Bold("标题"), "\n", "道友<&>_#[]()")
    page = RichPage(page="test", rich_html="<h1>标题</h1>", fallback=formatted)

    kwargs = regular_kwargs(formatted)

    assert kwargs["text"] == "标题\n道友<&>_#[]()"
    assert kwargs["parse_mode"] is None
    assert [entity.type for entity in kwargs["entities"]] == ["bold"]
    assert plain_text(page) == kwargs["text"]
    assert escape_rich_html("道友<&>\"") == "道友&lt;&amp;&gt;&quot;"
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_presentation.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'bot.presentation'`。

- [ ] **Step 3: 更新依赖与环境示例**

将 `requirements.txt` 首行改为：

```text
aiogram>=3.29,<4
```

在 `.env.example` 追加：

```text
# 是否启用 Bot API 10.1 Rich Messages；关闭时使用普通实体回退
RICH_MESSAGES_ENABLED=true
```

安装并确认版本：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c "import aiogram; print(aiogram.__version__)"
```

Expected: 输出版本不低于 `3.29.0` 且低于 `4.0.0`。

- [ ] **Step 4: 实现最小内容模型**

创建 `bot/presentation.py`：

```python
from __future__ import annotations

"""Telegram 消息展示：安全实体、Rich Message 与回退。"""

from dataclasses import dataclass
import html
import os
from typing import TypeAlias

from aiogram.utils.formatting import Text


@dataclass(frozen=True)
class RichPage:
    """同时保存 Rich HTML 与普通实体回退的报告型页面。"""

    page: str
    rich_html: str
    fallback: Text


MessageContent: TypeAlias = str | Text | RichPage
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def rich_messages_enabled() -> bool:
    raw = os.getenv("RICH_MESSAGES_ENABLED", "true")
    return raw.strip().lower() in _TRUE_VALUES


def escape_rich_html(value: object) -> str:
    return html.escape(str(value), quote=True)


def plain_text(content: MessageContent) -> str:
    if isinstance(content, RichPage):
        content = content.fallback
    if isinstance(content, Text):
        return str(content.as_kwargs()["text"])
    return content


def regular_kwargs(content: str | Text) -> dict:
    if isinstance(content, Text):
        return content.as_kwargs()
    return {"text": content}
```

- [ ] **Step 5: 运行内容模型测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_presentation.py -v`

Expected: PASS。

- [ ] **Step 6: 运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7: 提交 Task 1**

```bash
git add requirements.txt .env.example bot/presentation.py tests/test_presentation.py
git commit -m "建立 Telegram 混合消息模型"
```

---

### Task 2: 统一回复、编辑、主动发送与 Rich 回退

**Files:**
- Modify: `bot/presentation.py`
- Modify: `handlers/common.py:1-205`
- Modify: `tests/test_presentation.py`

**Interfaces:**
- Consumes: Task 1 的 `MessageContent`、`RichPage`、`regular_kwargs()`、`rich_messages_enabled()`。
- Produces: `answer(message, content: MessageContent, markup=None)`。
- Produces: `show(callback, content: MessageContent, markup=None)`。
- Produces: `send(bot, chat_id: int | str, content: MessageContent, markup=None)`。
- Preserves: `handlers.common.show(callback, text, markup)` 的既有导入路径和位置参数调用方式。

- [ ] **Step 1: 写发送与回退失败测试**

在 `tests/test_presentation.py` 追加 Fake 对象与测试：

```python
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.utils.formatting import Bold

from bot.presentation import answer, send, show


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessage(chat_id=1, text="占位"),
        message=message)


class FakeMessage:
    def __init__(self, edit_errors=None, rich_error=None):
        self.edit_errors = list(edit_errors or [])
        self.rich_error = rich_error
        self.edits = []
        self.answers = []

    async def edit_text(self, **kwargs):
        self.edits.append(kwargs)
        if self.edit_errors:
            raise self.edit_errors.pop(0)

    async def answer(self, **kwargs):
        self.answers.append(("regular", kwargs))

    async def answer_rich(self, **kwargs):
        self.answers.append(("rich", kwargs))
        if self.rich_error:
            raise self.rich_error


class FakeCallback:
    def __init__(self, message):
        self.message = message


class FakeBot:
    def __init__(self, rich_error=None):
        self.rich_error = rich_error
        self.sent = []

    async def send_message(self, **kwargs):
        self.sent.append(("regular", kwargs))

    async def send_rich_message(self, **kwargs):
        self.sent.append(("rich", kwargs))
        if self.rich_error:
            raise self.rich_error


@pytest.mark.asyncio
async def test_answer_and_send_choose_rich_or_fallback(monkeypatch):
    page = RichPage("test", "<h1>标题</h1>", Text(Bold("标题")))
    message = FakeMessage()
    bot = FakeBot()

    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")
    await answer(message, page)
    await send(bot, 7, page)
    assert message.answers[0][0] == "rich"
    assert bot.sent[0][0] == "rich"

    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "false")
    await answer(message, page)
    await send(bot, 7, page)
    assert message.answers[-1][0] == "regular"
    assert bot.sent[-1][0] == "regular"
    assert bot.sent[-1][1]["parse_mode"] is None


@pytest.mark.asyncio
async def test_answer_and_send_fall_back_after_rich_format_error(monkeypatch, caplog):
    error = _bad_request("Bad Request: can't parse rich message; 密文<&>")
    page = RichPage("report", "<h1>密文</h1>", Text(Bold("回退正文")))
    message = FakeMessage(rich_error=error)
    bot = FakeBot(rich_error=error)
    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")

    await answer(message, page)
    await send(bot, 7, page)

    assert [kind for kind, _kwargs in message.answers] == ["rich", "regular"]
    assert [kind for kind, _kwargs in bot.sent] == ["rich", "regular"]
    assert caplog.text.count("report") == 2
    assert "密文" not in caplog.text


@pytest.mark.asyncio
async def test_show_falls_back_only_for_rich_format_errors(monkeypatch, caplog):
    page = RichPage("battle", "<h1>战报</h1>", Text(Bold("战报")))
    rich_error = _bad_request("Bad Request: can't parse rich message; 密文<&>")
    message = FakeMessage(edit_errors=[rich_error])
    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")

    await show(FakeCallback(message), page)

    assert "rich_message" in message.edits[0]
    assert message.edits[1]["parse_mode"] is None
    assert message.answers == []
    assert "battle" in caplog.text
    assert "解析失败" in caplog.text
    assert "密文" not in caplog.text
    assert "<h1>战报</h1>" not in caplog.text


@pytest.mark.asyncio
async def test_show_handles_not_modified_and_uneditable_once():
    unchanged = FakeMessage(edit_errors=[_bad_request("message is not modified")])
    await show(FakeCallback(unchanged), "相同")
    assert unchanged.answers == []

    uneditable = FakeMessage(edit_errors=[_bad_request("message can't be edited")])
    await show(FakeCallback(uneditable), "补发")
    assert len(uneditable.answers) == 1


@pytest.mark.asyncio
async def test_unknown_bad_request_is_not_swallowed():
    message = FakeMessage(edit_errors=[_bad_request("chat not found")])
    with pytest.raises(TelegramBadRequest, match="chat not found"):
        await show(FakeCallback(message), "失败")

    rich_message = FakeMessage(rich_error=_bad_request("chat not found"))
    page = RichPage("test", "<h1>失败</h1>", Text("回退"))
    with pytest.raises(TelegramBadRequest, match="chat not found"):
        await answer(rich_message, page)
```

- [ ] **Step 2: 运行传输测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_presentation.py -v`

Expected: FAIL with `ImportError`，因为 `answer`、`show` 与 `send` 尚不存在。

- [ ] **Step 3: 实现窄范围错误分类与普通/Rich 发送**

在 `bot/presentation.py` 增加：

```python
import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputRichMessage

logger = logging.getLogger("xian.presentation")


def _is_not_modified(exc: TelegramBadRequest) -> bool:
    return "not modified" in str(exc).lower()


def _is_uneditable(exc: TelegramBadRequest) -> bool:
    text = str(exc).lower()
    return "message can't be edited" in text or "message to edit not found" in text


def _rich_error_category(exc: TelegramBadRequest) -> str | None:
    text = str(exc).lower()
    if "can't parse" in text and ("rich" in text or "entities" in text):
        return "解析失败"
    if "rich message" in text and (
            "unsupported" in text or "not supported" in text):
        return "接口不支持"
    return None


def _rich_input(page: RichPage) -> InputRichMessage:
    return InputRichMessage(html=page.rich_html)


async def answer(message, content: MessageContent, markup=None):
    if isinstance(content, RichPage) and rich_messages_enabled():
        try:
            return await message.answer_rich(
                rich_message=_rich_input(content), reply_markup=markup)
        except TelegramBadRequest as exc:
            category = _rich_error_category(exc)
            if category is None:
                raise
            logger.warning("Rich 页面 %s 回复降级：%s", content.page, category)
            content = content.fallback
    elif isinstance(content, RichPage):
        content = content.fallback
    return await message.answer(reply_markup=markup, **regular_kwargs(content))


async def send(bot, chat_id: int | str, content: MessageContent, markup=None):
    if isinstance(content, RichPage) and rich_messages_enabled():
        try:
            return await bot.send_rich_message(
                chat_id=chat_id,
                rich_message=_rich_input(content),
                reply_markup=markup)
        except TelegramBadRequest as exc:
            category = _rich_error_category(exc)
            if category is None:
                raise
            logger.warning("Rich 页面 %s 主动发送降级：%s", content.page, category)
            content = content.fallback
    elif isinstance(content, RichPage):
        content = content.fallback
    return await bot.send_message(
        chat_id=chat_id, reply_markup=markup, **regular_kwargs(content))
```

- [ ] **Step 4: 实现编辑、不可编辑补发和格式回退**

在同一模块增加：

```python
async def show(callback, content: MessageContent, markup=None):
    current: str | Text = content.fallback if isinstance(content, RichPage) else content
    if isinstance(content, RichPage) and rich_messages_enabled():
        try:
            return await callback.message.edit_text(
                rich_message=_rich_input(content), reply_markup=markup)
        except TelegramBadRequest as exc:
            if _is_not_modified(exc):
                return None
            if _is_uneditable(exc):
                return await answer(callback.message, content, markup)
            category = _rich_error_category(exc)
            if category is None:
                raise
            logger.warning("Rich 页面 %s 编辑降级：%s", content.page, category)

    try:
        return await callback.message.edit_text(
            reply_markup=markup, **regular_kwargs(current))
    except TelegramBadRequest as exc:
        if _is_not_modified(exc):
            return None
        if _is_uneditable(exc):
            return await answer(callback.message, current, markup)
        raise
```

在 `handlers/common.py` 删除原 `show()` 和不再需要的 `TelegramBadRequest` 导入，改为：

```python
from bot.presentation import show
```

其余 handler 继续从 `handlers.common` 导入 `show`，避免一次性修改全部文件。

- [ ] **Step 5: 运行传输测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_presentation.py -v`

Expected: PASS。

- [ ] **Step 6: 运行现有 callback 假对象测试**

Run: `.venv/bin/python -m pytest tests/test_market.py tests/test_economy.py tests/test_bonds_handlers.py tests/test_skills_natal_handlers.py -v`

Expected: PASS；纯字符串调用仍只传 `text` 与 `reply_markup`。

- [ ] **Step 7: 运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 8: 提交 Task 2**

```bash
git add bot/presentation.py handlers/common.py tests/test_presentation.py
git commit -m "统一 Telegram 消息发送与回退"
```

---

### Task 3: 将帮助与版本公告迁移为 RichPage

**Files:**
- Modify: `config/copy.py`
- Modify: `handlers/help.py`
- Create: `tests/test_rich_pages.py`
- Modify: `tests/test_daohang.py:250-275`

**Interfaces:**
- Consumes: Task 1 的 `RichPage`、`escape_rich_html()`、`plain_text()`。
- Consumes: Task 2 的 `answer()` 与 `show()`。
- Produces: `HELP_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]`，命令名不带 `/`。
- Produces: `render_help() -> RichPage`、`render_version_notice() -> RichPage`。

- [ ] **Step 1: 写帮助页结构失败测试**

创建 `tests/test_rich_pages.py`：

```python
from __future__ import annotations

import pytest
import pytest_asyncio

from bot.app import _COMMANDS
from bot.presentation import RichPage, plain_text
from config.copy import HELP_GROUPS
from handlers import help as help_handler
from models import db


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "rich-pages.db"))
    try:
        yield
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_help_groups_cover_every_registered_command(temp_db):
    page = await help_handler.render_help()
    grouped = [command for _group, rows in HELP_GROUPS for command, _desc in rows]

    assert isinstance(page, RichPage)
    assert len(HELP_GROUPS) == 4
    assert set(grouped) == {command.command for command in _COMMANDS}
    assert len(grouped) == len(set(grouped))
    assert page.rich_html.count("<h2>") == len(HELP_GROUPS) + 1
    assert page.rich_html.count("<li>") == len(grouped)
    assert sum(entity.type == "bot_command"
               for entity in page.fallback.as_kwargs()["entities"]) == len(grouped)


@pytest.mark.asyncio
async def test_version_notice_keeps_same_dynamic_notice_in_both_formats(temp_db, monkeypatch):
    notice = "宽限<&>_#[]()"

    async def fake_notice():
        return notice

    monkeypatch.setattr(help_handler.character, "overflow_grace_notice", fake_notice)

    page = await help_handler.render_version_notice()

    assert notice in plain_text(page)
    assert "宽限&lt;&amp;&gt;_#[]()" in page.rich_html
```

- [ ] **Step 2: 运行帮助页测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_rich_pages.py -v`

Expected: 测试收集阶段 FAIL with `ImportError`，因为 `HELP_GROUPS` 尚未定义。

- [ ] **Step 3: 将帮助文案改为四组静态数据**

在 `config/copy.py` 用以下形态替换单一 `HELP` 长字符串，并保证命令集合与 `bot.app._COMMANDS` 完全一致：

```python
HELP_INTRO = "道友初入仙途，可循以下法门："
HELP_OUTRO = "大道三千，愿道友早证长生。"
HELP_GROUPS = (
    ("修行养成", (
        ("start", "踏入仙途 / 测灵根"),
        ("me", "查看道行"),
        ("cultivate", "闭关 / 出关"),
        ("daily", "每日签到"),
        ("quest", "悬赏任务"),
        ("bag", "储物袋"),
    )),
    ("历练斗法", (
        ("explore", "历练刷怪"),
        ("dungeon", "秘境副本"),
        ("pvp", "群内切磋"),
        ("rank", "天梯排行"),
        ("boss", "世界 Boss"),
        ("weekly", "周活动副本"),
    )),
    ("经营交易", (
        ("craft", "炼丹炼器"),
        ("skills", "法宝 / 功法"),
        ("shop", "NPC 商店"),
        ("market", "玩家坊市"),
        ("auction", "拍卖行"),
    )),
    ("宗门社交", (
        ("sect", "宗门"),
        ("master", "师徒"),
        ("partner", "道侣共修"),
        ("path", "道途 / 转修"),
        ("ascension", "飞升试炼"),
        ("sectwar", "宗门战据点"),
        ("help", "重览此卷"),
    )),
)
```

- [ ] **Step 4: 构造 Rich HTML 与实体回退**

在 `handlers/help.py`：

- 用 `Bold`、`BotCommand`、`Italic`、`Text` 构造实体回退；
- Rich HTML 使用 `<h1>`、四个 `<h2>`、`<ul><li>` 和 `<p>`；
- 命令在 HTML 中保持裸 `/command`，让 Telegram 自动识别；
- `overflow_grace_notice()` 的结果分别作为 `Text` 节点和 `escape_rich_html()` 后的 `<p>` 内容；
- `cmd_help()` 改为 `await answer(message, await render_help(), main_menu_return_markup())`。

核心构造形态：

```python
def _commands_fallback(notice: str) -> Text:
    parts = [Bold("📜 问道·指南"), "\n", Italic(HELP_INTRO)]
    for group, rows in HELP_GROUPS:
        parts.extend(["\n\n", Bold(group)])
        for command, description in rows:
            parts.extend([
                "\n• ", BotCommand(f"/{command}"), " — ", description])
    parts.extend([
        "\n\n", Italic(HELP_OUTRO),
        "\n\n", Bold(OVERFLOW_NOTICE_TITLE), "\n", notice])
    return Text(*parts)


def _commands_html(notice: str) -> str:
    groups = []
    for group, rows in HELP_GROUPS:
        items = "".join(
            f"<li>/{command} — {escape_rich_html(description)}</li>"
            for command, description in rows)
        groups.append(f"<h2>{escape_rich_html(group)}</h2><ul>{items}</ul>")
    return (
        "<h1>📜 问道·指南</h1>"
        f"<p><i>{escape_rich_html(HELP_INTRO)}</i></p>"
        + "".join(groups)
        + f"<p><i>{escape_rich_html(HELP_OUTRO)}</i></p>"
        + f"<h2>{escape_rich_html(OVERFLOW_NOTICE_TITLE)}</h2>"
        + f"<p>{escape_rich_html(notice)}</p>")


async def render_help() -> RichPage:
    notice = await character.overflow_grace_notice()
    return RichPage(
        page="help",
        rich_html=_commands_html(notice),
        fallback=_commands_fallback(notice),
    )


async def render_version_notice() -> RichPage:
    notice = await character.overflow_grace_notice()
    return RichPage(
        page="version_notice",
        rich_html=(
            f"<h1>{escape_rich_html(VERSION_NOTICE_TITLE)}</h1>"
            f"<p>{escape_rich_html(notice)}</p>"),
        fallback=Text(Bold(VERSION_NOTICE_TITLE), "\n", notice),
    )
```

`render_version_notice()` 使用独立页面，不复用帮助页完整正文。

- [ ] **Step 5: 更新既有文本断言**

在 `tests/test_daohang.py` 导入 `plain_text`，将：

```python
version_notice = await help_handler.render_version_notice()
help_text = await help_handler.render_help()
```

改为：

```python
version_notice = plain_text(await help_handler.render_version_notice())
help_text = plain_text(await help_handler.render_help())
```

其余业务语义断言保持不变。

- [ ] **Step 6: 运行帮助页相关测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_rich_pages.py tests/test_daohang.py -v`

Expected: PASS。

- [ ] **Step 7: 运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 8: 提交 Task 3**

```bash
git add config/copy.py handlers/help.py tests/test_rich_pages.py tests/test_daohang.py
git commit -m "优化帮助与公告富文本展示"
```

---

### Task 4: 将角色面板迁移为安全实体

**Files:**
- Modify: `handlers/me.py:21-74`
- Modify: `tests/test_rich_pages.py`
- Modify: `tests/test_playability_issues.py`
- Modify: `tests/test_bonds_handlers.py`
- Modify: `tests/test_daohang.py`

**Interfaces:**
- Consumes: Task 1 的 `MessageContent`、`plain_text()`。
- Consumes: Task 2 的 `answer()` 与 `show()`。
- Produces: `render_me(user_id: int) -> tuple[str | Text, InlineKeyboardMarkup | None]`；角色存在时返回 `Text`，缺失时仍返回 `NEED_START`。

- [ ] **Step 1: 写角色面板结构失败测试**

在 `tests/test_rich_pages.py` 追加：

```python
from aiogram.utils.formatting import Text

from handlers import me as me_handler
from services import character


@pytest.mark.asyncio
async def test_me_panel_uses_bold_sections_without_losing_dynamic_values(temp_db):
    uid = 98101
    await character.create(uid, "面板<&>_#[]()")
    await character.add_stone(uid, 4321)

    content, markup = await me_handler.render_me(uid)
    text = plain_text(content)
    entity_types = [entity.type for entity in content.as_kwargs()["entities"]]

    assert isinstance(content, Text)
    assert str(4321) in text
    assert entity_types.count("bold") >= 4
    assert markup is not None
```

不要断言固定中文句子；使用动态灵石、装备、成就或关系值验证数据未丢失。

- [ ] **Step 2: 运行角色面板测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_rich_pages.py::test_me_panel_uses_bold_sections_without_losing_dynamic_values -v`

Expected: FAIL，因为当前 `render_me()` 返回纯字符串。

- [ ] **Step 3: 用 Text 节点重组角色面板**

保留当前全部查询与业务判断，只替换最终 `lines` 拼接。结构固定为：

```python
content = Text(
    Bold(f"📜 {char.spirit_root} · 根骨 {char.root_bone}"),
    "\n", Bold("境界与资源"),
    "\n", f"境界：{R.realm_label(char.realm, char.stage)} {seclusion}",
    "\n", f"修为：{char.cultivation}/{cost}  {progress_bar(char.cultivation, cost)}",
    "\n", f"🪙 灵石 {char.spirit_stone}　⚡ 精力 {char.stamina}/{cap}",
    "\n\n", Bold("法身六维"),
    "\n", f"气血 {v['hp']}/{v['max_hp']}　法力 {v['mp']}/{v['max_mp']}",
    "\n", f"攻击 {st['atk']}　防御 {st['df']}　身法 {st['spd']}　暴击 {st['crit']}",
    "\n\n", Bold("法宝功法"),
    "\n", f"⚔️ 法宝：{item_name(weapon_key)}",
    "\n", "📖 心法：", skill_name(mind) if mind else "无",
    "\n", "📖 战技：", "、".join(skill_name(s) for s in skills) if skills else "无",
    "\n\n", Bold("关系与状态"),
    *status_parts,
)
```

`status_parts` 由现有道侣、溢出、道基不稳与成就判断生成，每项以 `"\n"` 开头；无任何状态时加入 `"\n暂无异状"`。动态名字作为普通字符串节点，不包在 HTML 或格式标记内。

`cmd_me()` 改为：

```python
await answer(message, content, markup)
```

- [ ] **Step 4: 更新既有角色面板测试读取方式**

在 `tests/test_playability_issues.py`、`tests/test_bonds_handlers.py` 和 `tests/test_daohang.py` 中，对 `render_me()` 返回的第一项调用 `plain_text()` 后再执行原有动态值断言：

```python
content, _ = await me_handler.render_me(uid)
text = plain_text(content)
```

- [ ] **Step 5: 运行角色面板相关测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_rich_pages.py tests/test_playability_issues.py tests/test_bonds_handlers.py tests/test_daohang.py -v`

Expected: PASS。

- [ ] **Step 6: 运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 7: 提交 Task 4**

```bash
git add handlers/me.py tests/test_rich_pages.py tests/test_playability_issues.py tests/test_bonds_handlers.py tests/test_daohang.py
git commit -m "重排角色面板信息层级"
```

---

### Task 5: 将历练、秘境和 PvP 成功结算迁移为折叠战报

**Files:**
- Modify: `handlers/common.py`
- Modify: `handlers/explore.py:111-169`
- Modify: `handlers/dungeon.py:64-112`
- Modify: `handlers/pvp.py:29-43`
- Modify: `tests/test_rich_pages.py`
- Modify: `tests/test_vitals.py:160-195`

**Interfaces:**
- Consumes: Task 1 的 `RichPage`、`escape_rich_html()`、`plain_text()`。
- Produces: `battle_report_page(*, page: str, title: str, outcome: str, log: list[str], rewards: list[str], status: list[str]) -> RichPage`。
- Preserves: `handlers.explore._result_text()`、`handlers.dungeon._result_text()` 与 `handlers.pvp._text()` 对非成功 `status` 返回原有纯字符串。

- [ ] **Step 1: 写共享战报结构失败测试**

在 `tests/test_rich_pages.py` 追加：

```python
from handlers.common import battle_report_page


def test_battle_report_hides_log_but_keeps_summary_visible():
    marker = "日志<&>_#[]()"
    page = battle_report_page(
        page="test_battle",
        title="⚔️ 战报",
        outcome="大捷",
        log=[marker],
        rewards=["灵石 123"],
        status=["气血 10/20", "精力余 7"],
    )
    fallback_entities = page.fallback.as_kwargs()["entities"]

    assert "<details>" in page.rich_html
    assert "日志&lt;&amp;&gt;_#[]()" in page.rich_html
    assert page.rich_html.index("<details>") < page.rich_html.index("灵石 123")
    assert any(entity.type == "expandable_blockquote" for entity in fallback_entities)
    assert all(value in plain_text(page)
               for value in (marker, "123", "10/20", "7"))
```

- [ ] **Step 2: 运行共享战报测试并确认按预期失败**

Run: `.venv/bin/python -m pytest tests/test_rich_pages.py::test_battle_report_hides_log_but_keeps_summary_visible -v`

Expected: FAIL with `ImportError`，因为 `battle_report_page` 尚不存在。

- [ ] **Step 3: 实现共享战报构造器**

在 `handlers/common.py` 增加：

```python
from aiogram.utils.formatting import Bold, ExpandableBlockQuote, Text

from bot.presentation import RichPage, escape_rich_html, show


def battle_report_page(
        *, page: str, title: str, outcome: str, log: list[str],
        rewards: list[str], status: list[str]) -> RichPage:
    log_text = "\n".join(log) if log else "斗法无可记述。"
    fallback_parts = [
        Bold(title), "\n", outcome,
        "\n\n", ExpandableBlockQuote(Bold("斗法经过"), "\n", log_text),
    ]
    if rewards:
        fallback_parts.extend([
            "\n\n", Bold("所得机缘"),
            *[part for row in rewards for part in ("\n", row)],
        ])
    if status:
        fallback_parts.extend([
            "\n\n", Bold("当前状态"),
            *[part for row in status for part in ("\n", row)],
        ])
    reward_html = "" if not rewards else (
        "<h2>所得机缘</h2><ul>" +
        "".join(f"<li>{escape_rich_html(row)}</li>" for row in rewards) +
        "</ul>")
    status_html = "" if not status else (
        "<h2>当前状态</h2><ul>" +
        "".join(f"<li>{escape_rich_html(row)}</li>" for row in status) +
        "</ul>")
    rich_html = (
        f"<h1>{escape_rich_html(title)}</h1>"
        f"<p><b>{escape_rich_html(outcome)}</b></p>"
        "<details><summary>斗法经过</summary>"
        + "".join(f"<p>{escape_rich_html(row)}</p>" for row in log)
        + "</details>" + reward_html + status_html)
    return RichPage(
        page=page,
        rich_html=rich_html,
        fallback=Text(*fallback_parts))
```

- [ ] **Step 4: 写三类结果转换失败测试**

在 `tests/test_rich_pages.py` 追加：

```python
def _assert_rich_result(content, expected_values):
    assert isinstance(content, RichPage)
    assert "<details>" in content.rich_html
    assert any(entity.type == "expandable_blockquote"
               for entity in content.fallback.as_kwargs()["entities"])
    text = plain_text(content)
    assert all(str(value) in text for value in expected_values)


def _vitals():
    return {
        "battle_hp_before": 90,
        "battle_hp_after": 71,
        "battle_mp_before": 80,
        "battle_mp_after": 66,
        "hp_after": 75,
        "mp_after": 70,
        "max_hp": 100,
        "max_mp": 100,
    }


def test_explore_result_becomes_rich_report():
    content = explore_handler._result_text({
        "status": "ok",
        "map": "断云岭<&>",
        "win": True,
        "sweep": False,
        "is_boss": False,
        "log": ["一剑破敌_#[]()"],
        "reward": {"stone": 321, "cult": 45, "daohang": 6, "drops": {}},
        "stamina_left": 17,
        **_vitals(),
    })

    _assert_rich_result(content, ("断云岭<&>", "321", "45", "17", "71"))


def test_dungeon_result_becomes_rich_report():
    content = dungeon_handler._result_text({
        "status": "ok",
        "dungeon": "玄霜秘境<&>",
        "cleared": 3,
        "layers": 5,
        "win": False,
        "defeat_reason": "hp_zero",
        "log": ["第三层力竭_#[]()"],
        "reward": {
            "stone": 654,
            "cult": 87,
            "daohang": 9,
            "drops": {},
            "equipment": ["玄霜剑<&>"],
        },
        "stamina_left": 13,
        **_vitals(),
    })

    _assert_rich_result(content, ("玄霜秘境<&>", "3/5", "654", "玄霜剑<&>", "13"))


def test_pvp_result_becomes_rich_report():
    content = pvp_handler._text({
        "status": "ok",
        "attacker_name": "攻方<&>_#[]()",
        "defender_name": "守方<&>_#[]()",
        "win": True,
        "finish_reason": "hp_zero",
        "log": ["剑气纵横<&>_#[]()"],
        "rating_delta": 19,
        "tier": "金丹",
        "reputation_gain": 3,
        "reputation_counted": True,
    })

    _assert_rich_result(content, ("攻方<&>_#[]()", "守方<&>_#[]()", "+19", "声望 +3"))


@pytest.mark.parametrize("renderer", [
    explore_handler._result_text,
    dungeon_handler._result_text,
    pvp_handler._text,
])
def test_non_success_battle_status_stays_plain(renderer):
    assert isinstance(renderer({"status": "missing"}), str)
```

并在文件顶部导入：

```python
from handlers import (dungeon as dungeon_handler, explore as explore_handler,
                      pvp as pvp_handler)
```

Run: `.venv/bin/python -m pytest tests/test_rich_pages.py -v`

Expected: FAIL，因为三个成功分支仍返回纯字符串。

- [ ] **Step 5: 迁移三个成功结算分支**

保持现有状态判断、日志截断和奖励计算，只把最终成功分支改为调用 `battle_report_page()`：

```python
return battle_report_page(
    page="explore_result",
    title=f"⚔️ {res['map']}·{'大捷' if res['win'] else '重伤而归'}",
    outcome=outcome,
    log=shown,
    rewards=reward_lines,
    status=battle_vitals_lines(res) + [f"⚡ 精力余 {res['stamina_left']}"],
)
```

秘境使用 `page="dungeon_result"`，标题包含秘境名和深入层数；PvP 使用 `page="pvp_result"`，标题包含攻守双方名，`outcome` 保留 `_outcome_text()`、天梯积分、段位和声望信息。PvP 无独立资源掉落时传 `rewards=[]`，把积分与声望放在 `status`，并在 Rich 与实体回退的战报摘要中明确显示“本场不消耗气血、法力与精力”（切磋资源例外不修改服务层数值或重新查询资源）。

`handlers/explore.py`、`handlers/dungeon.py` 的命令首页仍为纯字符串；本任务只迁移 `status == "ok"` 的结算。三个 callback 继续调用统一 `show()`，按钮标记不变。

- [ ] **Step 6: 更新既有战报文本断言**

在 `tests/test_vitals.py`：

1. 从 `bot.presentation` 导入 `plain_text`；
2. 在 `test_explore_timeout_loss_text_explains_remaining_hp()` 中，将现有赋值左侧的 `text` 政名为 `content`，保留完整结果字典不变；
3. 在结果字典调用结束后紧接一行 `text = plain_text(content)`。

保留当前关于久战判负和战斗气血快照的断言，不改变业务期望。

- [ ] **Step 7: 运行战报相关测试并确认通过**

Run: `.venv/bin/python -m pytest tests/test_rich_pages.py tests/test_vitals.py -v`

Expected: PASS。

- [ ] **Step 8: 运行完整回归**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 9: 提交 Task 5**

```bash
git add handlers/common.py handlers/explore.py handlers/dungeon.py handlers/pvp.py tests/test_rich_pages.py tests/test_vitals.py
git commit -m "折叠历练秘境与切磋战报"
```

---

### Task 6: 第一批验收与第二批规划关口

**Files:**
- Verify: `docs/superpowers/specs/2026-07-14-telegram-rich-presentation-design.md`
- Verify: all files modified in Tasks 1-5

**Interfaces:**
- Consumes: `RichPage`、`MessageContent`、`answer()`、`show()`、`send()`、`battle_report_page()`。
- Produces: 可供第二批面板和通知迁移复用的稳定展示接口；本任务不新增代码接口。

- [ ] **Step 1: 运行静态差异检查**

Run: `git diff --check`

Expected: 无输出。

- [ ] **Step 2: 确认未启用全局 parse_mode**

Run: `rg -n "DefaultBotProperties|parse_mode=ParseMode|Bot\(.*parse_mode" bot handlers services`

Expected: 不出现全局 `parse_mode` 配置；只允许测试或 `Text.as_kwargs()` 生成的 `parse_mode=None`。

- [ ] **Step 3: 确认动态 HTML 入口集中**

Run: `rg -n "<h[1-6]>|<details>|<ul>|<li>" handlers bot --glob '*.py'`

Expected: Rich HTML 仅出现在 `handlers/help.py`、`handlers/common.py` 和 `bot/presentation.py` 的受控构造路径中；不存在把玩家名或宗门名直接插入未转义 HTML 的代码。

- [ ] **Step 4: 运行完整测试**

Run: `.venv/bin/python -m pytest`

Expected: 全量 PASS。

- [ ] **Step 5: 使用测试 Bot 做人工冒烟**

以测试 token 启动：

```bash
RICH_MESSAGES_ENABLED=true .venv/bin/python -m bot
```

依次验证 `/help`、`/me`、一次历练结算、一次秘境结算和一次群内 PvP：标题与列表正常，战斗日志默认折叠，按钮编辑正常。使用包含 `<>&_*#[]()` 的 Telegram 显示名验证正文不破损。

关闭进程后重启回退模式：

```bash
RICH_MESSAGES_ENABLED=false .venv/bin/python -m bot
```

再次验证同一组入口均显示完整实体版本，callback 与按钮行为不变。

- [ ] **Step 6: 记录第一批验收结果**

若人工冒烟无需代码修复，不创建空提交；在执行记录中记下 Telegram 客户端、Rich 开关两种模式和全量测试结果。若发现问题，回到对应 Task 的测试先复现，再修复并重新运行完整测试。

第一批通过后，再依据同一设计文档为“其余交互面板与主动通知”编写独立第二批计划；第二批不得改变本计划已经稳定的公共接口。
