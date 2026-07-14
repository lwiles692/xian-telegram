from __future__ import annotations

import pytest

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.utils.formatting import Bold, Text

from bot.presentation import (RichPage, answer, escape_rich_html, plain_text,
                              regular_kwargs, rich_messages_enabled, send,
                              show)


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


class RichEditMessage(FakeMessage):
    async def edit_text(self, rich_message=None, **kwargs):
        if rich_message is not None:
            kwargs["rich_message"] = rich_message
        self.edits.append(kwargs)
        if self.edit_errors:
            raise self.edit_errors.pop(0)


class RegularEditMessage(FakeMessage):
    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup, **kwargs})
        if self.edit_errors:
            raise self.edit_errors.pop(0)


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
    message = RichEditMessage(edit_errors=[rich_error])
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
async def test_show_uses_rich_when_edit_text_declares_rich_message(monkeypatch):
    page = RichPage("declared", "<h1>战报</h1>", Text(Bold("战报")))
    message = RichEditMessage()
    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")

    await show(FakeCallback(message), page)

    assert "rich_message" in message.edits[0]
    assert "text" not in message.edits[0]


@pytest.mark.asyncio
async def test_show_uses_regular_when_edit_text_lacks_rich_message(monkeypatch):
    page = RichPage("undeclared", "<h1>战报</h1>", Text(Bold("战报")))
    message = RegularEditMessage()
    monkeypatch.setenv("RICH_MESSAGES_ENABLED", "true")

    await show(FakeCallback(message), page)

    assert message.edits[0]["text"] == "战报"
    assert message.edits[0]["parse_mode"] is None


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
