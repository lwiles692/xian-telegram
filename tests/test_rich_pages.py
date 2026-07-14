from __future__ import annotations

import pytest
import pytest_asyncio
from aiogram.utils.formatting import Text

from bot.app import _COMMANDS
from bot.presentation import RichPage, plain_text
from config.copy import HELP_GROUPS
from handlers import (dungeon as dungeon_handler, explore as explore_handler,
                      pvp as pvp_handler)
from handlers import help as help_handler
from handlers import me as me_handler
from models import db
from services import character


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


@pytest.mark.asyncio
async def test_me_panel_uses_bold_sections_without_losing_dynamic_values(temp_db):
    uid = 98101
    await character.create(uid, "面板<&>_#[]()")
    await character.add_stone(uid, 4321)

    content, markup = await me_handler.render_me(uid)
    text = plain_text(content)
    entity_types = [entity.type for entity in content.as_kwargs()["entities"]]
    expected_stone = (await character.get(uid)).spirit_stone

    assert isinstance(content, Text)
    assert str(expected_stone) in text
    assert entity_types.count("bold") >= 4
    assert markup is not None


def test_battle_report_hides_log_but_keeps_summary_visible():
    from handlers.common import battle_report_page

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
    assert all(value in plain_text(page) for value in (marker, "123", "10/20", "7"))


def test_battle_report_uses_same_placeholder_for_empty_log_in_both_formats():
    from handlers.common import battle_report_page

    page = battle_report_page(
        page="empty_battle",
        title="⚔️ 战报",
        outcome="无胜负",
        log=[],
        rewards=[],
        status=[],
    )

    assert "斗法无可记述。" in plain_text(page)
    assert "斗法无可记述。" in page.rich_html


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

    _assert_rich_result(content, ("攻方<&>_#[]()", "守方<&>_#[]()", "+19", "声望 +3",
                                  "本场不消耗气血、法力与精力"))
    assert "本场不消耗气血、法力与精力" in content.rich_html


@pytest.mark.parametrize("renderer", [
    explore_handler._result_text,
    dungeon_handler._result_text,
    pvp_handler._text,
])
def test_non_success_battle_status_stays_plain(renderer):
    assert isinstance(renderer({"status": "missing"}), str)
