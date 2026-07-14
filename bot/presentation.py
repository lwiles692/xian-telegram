from __future__ import annotations

"""Telegram 消息展示：安全实体、Rich Message 与回退。"""

from dataclasses import dataclass
import html
import logging
import os
from typing import Union

try:
    from typing import TypeAlias
except ImportError:  # Python 3.9 兼容
    TypeAlias = object

from aiogram.exceptions import TelegramBadRequest
try:
    from aiogram.types import InputRichMessage
except ImportError:  # aiogram 3.22 本地环境尚未提供 Rich 类型
    class InputRichMessage:
        def __init__(self, *, html: str):
            self.html = html

from aiogram.utils.formatting import Text


logger = logging.getLogger("xian.presentation")


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


def _is_not_modified(exc: TelegramBadRequest) -> bool:
    return "not modified" in str(exc).lower()


def _is_uneditable(exc: TelegramBadRequest) -> bool:
    text = str(exc).lower()
    return ("message can't be edited" in text
            or "message to edit not found" in text)


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
    if (isinstance(content, RichPage) and rich_messages_enabled()
            and callable(getattr(message, "answer_rich", None))):
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
    if (isinstance(content, RichPage) and rich_messages_enabled()
            and callable(getattr(bot, "send_rich_message", None))):
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


async def show(callback, content: MessageContent, markup=None):
    current: str | Text = (content.fallback
                            if isinstance(content, RichPage) else content)
    if (isinstance(content, RichPage) and rich_messages_enabled()
            and callable(getattr(callback.message, "answer_rich", None))):
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
