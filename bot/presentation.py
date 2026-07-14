from __future__ import annotations

"""Telegram 消息展示：安全实体、Rich Message 与回退。"""

from dataclasses import dataclass
import html
import os
from typing import Union

try:
    from typing import TypeAlias
except ImportError:  # Python 3.9 兼容
    TypeAlias = object

from aiogram.utils.formatting import Text


@dataclass(frozen=True)
class RichPage:
    """同时保存 Rich HTML 与普通实体回退的报告型页面。"""

    page: str
    rich_html: str
    fallback: Text


MessageContent: TypeAlias = Union[str, Text, RichPage]
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
