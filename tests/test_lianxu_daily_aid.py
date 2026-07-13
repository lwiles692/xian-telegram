from __future__ import annotations

import pytest
import pytest_asyncio

from config import realms as R
from handlers import daily as daily_handler
from models import db
from services import character, daily


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "lianxu-daily-aid.db"))
    yield
    await db.close_db()


@pytest.mark.asyncio
async def test_daily_checkin_grants_bound_lianxu_aid_at_huashen_full(temp_db):
    uid = 9801
    last_huashen = R.num_stages(4) - 1
    await character.create(uid, "化神圆满")
    await character.set_progress(uid, 4, last_huashen, R.advance_cost(4, last_huashen))

    first = await daily.checkin(uid, now=1000)
    second = await daily.checkin(uid, now=1001)

    assert first["status"] == "ok"
    assert first["extra_items"] == [{
        "item": "炼虚丹",
        "qty": 1,
        "bound": 1,
        "reason": "huashen_full_aid",
    }]
    assert "炼虚丹 ×1（绑定）" in daily_handler._ok_text(first)
    assert second["status"] == "done"
    assert await character.item_qty(uid, "炼虚丹", bound=1) == 1
    assert await character.item_qty(uid, "炼虚丹", bound=0) == 0


@pytest.mark.asyncio
async def test_daily_lianxu_aid_requires_full_cultivation_no_tribulation_and_no_pill(
        temp_db):
    last_huashen = R.num_stages(4) - 1
    cost = R.advance_cost(4, last_huashen)

    not_full = 9802
    await character.create(not_full, "未满化神")
    await character.set_progress(not_full, 4, last_huashen, cost - 1)
    result = await daily.checkin(not_full, now=1000)
    assert result["extra_items"] == []
    assert await character.item_qty(not_full, "炼虚丹") == 0

    already_has = 9803
    await character.create(already_has, "已有炼虚丹")
    await character.set_progress(already_has, 4, last_huashen, cost)
    await character.add_item(already_has, "炼虚丹", 1, bound=0)
    result = await daily.checkin(already_has, now=1000)
    assert result["extra_items"] == []
    assert await character.item_qty(already_has, "炼虚丹", bound=0) == 1

    in_tribulation = 9804
    await character.create(in_tribulation, "虚空劫中")
    await character.set_progress(in_tribulation, 4, last_huashen, cost)
    await db.execute(
        "INSERT INTO tribulation_sessions("
        "user_id, source_realm, source_stage, target_realm, target_stage, "
        "cultivation, cost, rate, hp, seed, created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (in_tribulation, 4, last_huashen, 5, 0, cost, cost, 0.5, 1, 1, 1000),
    )
    result = await daily.checkin(in_tribulation, now=1000)
    assert result["extra_items"] == []
    assert await character.item_qty(in_tribulation, "炼虚丹") == 0
