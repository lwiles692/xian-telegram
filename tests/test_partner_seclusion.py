from __future__ import annotations

import pytest
import pytest_asyncio

from config import bonds as BONDS
from models import db
from services import character, settle


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "partner-seclusion.db"))
    yield
    await db.close_db()


async def _备好角色(user_id: int, name: str):
    await character.create(user_id, name)
    await character.set_progress(user_id, 3, 0, 0)
    await db.execute(
        "UPDATE characters SET root_bone=0, cultivation=0 WHERE user_id=?",
        (user_id,))


async def _结为道侣(a_id: int, b_id: int, now: int):
    await db.execute(
        "INSERT INTO social_bonds(kind, a_id, b_id, status, created_at, "
        "activated_at, confirmed_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (BONDS.KIND_PARTNER, a_id, b_id, BONDS.STATUS_ACTIVE, now, now, now, now))
    await db.execute(
        "INSERT INTO social_bonds(kind, a_id, b_id, status, created_at, "
        "activated_at, confirmed_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (BONDS.KIND_PARTNER, b_id, a_id, BONDS.STATUS_ACTIVE, now, now, now, now))


def test_双修重叠纯函数_先截断闭关区间再求交():
    hour = 3600

    assert settle.partner_seclusion_overlap_seconds(
        0, 20 * hour, 13 * hour, 14 * hour) == 0
    assert settle.partner_seclusion_overlap_seconds(
        0, 20 * hour, 11 * hour, 13 * hour) == hour
    assert settle.partner_seclusion_overlap_seconds(
        0, 20 * hour, 0, None) == settle.OFFLINE_CAP_HOURS * hour


def test_双修额外收益纯函数_按重叠秒数与百分比折算():
    overlap = 6 * 3600

    expected = (
        settle.partner_seclusion_extra_units(
            3, 0, overlap, root_bone=0,
            partner_pct=settle.PARTNER_SECLUSION_PCT)
        // settle.CULTIVATION_SCALE
    )

    assert settle.partner_seclusion_extra_gain(
        3, 0, overlap, root_bone=0,
        partner_pct=settle.PARTNER_SECLUSION_PCT) == expected
    assert expected > 0


def test_收功文案展示道侣同参分钟与额外修为():
    from handlers.cultivate import _collect_text

    text = _collect_text({
        "minutes": 120,
        "gained": 1000,
        "cultivation": 1000,
        "cost": 2000,
        "can_advance": False,
        "partner_overlap_seconds": 4200,
        "partner_extra_cultivation": 42,
    })

    assert "与道侣同参 70 分钟，双修额外修为 +42" in text


@pytest.mark.asyncio
async def test_闭关区间列_开库幂等存在(temp_db):
    cols = {
        row["name"]
        for row in await db.fetchall("PRAGMA table_info(characters)")
    }

    assert {"last_seclusion_start", "last_seclusion_end"} <= cols


@pytest.mark.asyncio
async def test_主动收功写回最近区间并供道侣折算(temp_db):
    user_id = 8101
    partner_id = 8102
    await _备好角色(user_id, "同参甲")
    await _备好角色(partner_id, "同参乙")
    await _结为道侣(user_id, partner_id, now=900)

    await character.start_seclusion(partner_id, now=1000)
    partner_done = await character.collect_seclusion(partner_id, now=4600)
    partner_row = await db.fetchone(
        "SELECT last_seclusion_start, last_seclusion_end FROM characters WHERE user_id=?",
        (partner_id,))

    await character.start_seclusion(user_id, now=2800)
    result = await character.collect_seclusion(user_id, now=6400)
    user_row = await db.fetchone(
        "SELECT cultivation, last_seclusion_start, last_seclusion_end "
        "FROM characters WHERE user_id=?",
        (user_id,))
    expected_overlap = 1800
    expected_gain, _ = settle.seclusion_gain_with_remainder(
        3, 0, 2800, 6400, root_bone=0,
        partner_overlap_seconds=expected_overlap,
        partner_pct=settle.PARTNER_SECLUSION_PCT)

    assert partner_done["status"] == "collected"
    assert dict(partner_row) == {
        "last_seclusion_start": 1000,
        "last_seclusion_end": 4600,
    }
    assert result["status"] == "collected"
    assert result["partner_id"] == partner_id
    assert result["partner_overlap_seconds"] == expected_overlap
    assert result["partner_extra_cultivation"] == settle.partner_seclusion_extra_gain(
        3, 0, expected_overlap, root_bone=0,
        partner_pct=settle.PARTNER_SECLUSION_PCT)
    assert result["gained"] == expected_gain
    assert user_row["cultivation"] == expected_gain
    assert user_row["last_seclusion_start"] == 2800
    assert user_row["last_seclusion_end"] == 6400


@pytest.mark.asyncio
async def test_主动收功与返回自动收功_双修折算口径一致(temp_db):
    active_id = 8201
    active_partner = 8202
    auto_id = 8203
    auto_partner = 8204
    for uid, name in (
            (active_id, "主动同参"),
            (active_partner, "主动道侣"),
            (auto_id, "自动同参"),
            (auto_partner, "自动道侣"),
    ):
        await _备好角色(uid, name)
    await _结为道侣(active_id, active_partner, now=1000)
    await _结为道侣(auto_id, auto_partner, now=1000)
    for partner_id in (active_partner, auto_partner):
        await db.execute(
            "UPDATE characters SET last_seclusion_start=?, last_seclusion_end=? "
            "WHERE user_id=?",
            (4600, 8200, partner_id))

    await character.start_seclusion(active_id, now=4600)
    active = await character.collect_seclusion(active_id, now=8200)
    await db.execute(
        "UPDATE users SET last_seen_at=? WHERE tg_user_id=?",
        (1000, auto_id))
    auto = await character.touch_activity(auto_id, "自动同参", now=8200)
    auto_row = await db.fetchone(
        "SELECT cultivation, last_seclusion_start, last_seclusion_end "
        "FROM characters WHERE user_id=?",
        (auto_id,))

    assert active["partner_overlap_seconds"] == auto["auto_partner_overlap_seconds"]
    assert active["partner_extra_cultivation"] == auto["auto_partner_extra_cultivation"]
    assert active["gained"] == auto["auto_cultivation"]
    assert auto_row["cultivation"] == active["gained"]
    assert auto_row["last_seclusion_start"] == 4600
    assert auto_row["last_seclusion_end"] == 8200
