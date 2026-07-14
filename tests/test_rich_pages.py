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
