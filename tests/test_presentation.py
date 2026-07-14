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
