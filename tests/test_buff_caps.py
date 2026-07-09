from __future__ import annotations

import json

import pytest
import pytest_asyncio

from config import buffs as BUFFS
from config import bonds as BONDS_CFG
from config import events as EVENT_CFG
from config import realms as R
from models import db
from services import bonds, character, dao_path, items, settle


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "buff-caps.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _备好师徒(mentor_id: int, disciple_id: int, now: int, confirm: bool = True):
    await character.create(mentor_id, f"传功师尊{mentor_id}")
    await character.set_progress(mentor_id, 3, 0, 0)
    await character.create(disciple_id, f"传承弟子{disciple_id}")
    await character.set_progress(disciple_id, 0, 0, 0)
    pending = await bonds.create_pending_mentor_request(
        mentor_id, disciple_id, initiator_id=mentor_id, now=now)
    assert pending["status"] == "ok"
    if confirm:
        confirmed = await bonds.confirm_pending_mentor_request(
            pending["bond_id"], confirmer_id=disciple_id, now=now + 1)
        assert confirmed["status"] == "ok"
    return pending["bond_id"]


@pytest.mark.asyncio
async def test_attack_percent_buffs_are_clamped(temp_db):
    uid = 9201
    await character.create(uid, "atkcap")
    await character.create_item_instance(uid, "玄铁剑", affixes={"atk_pct": 0.20})
    inst = (await character.item_instances(uid))[0]
    await character.equip_instance(uid, inst["id"])
    await character.add_item(uid, "虎力丹", 1)
    await items.use(uid, "虎力丹")

    st = await character.stats(await character.get_at(uid, now=1000))
    raw = R.base_stats(0, 0)["atk"] + 38

    assert st["atk"] == int(raw * (1 + BUFFS.ATTACK_PCT_CAP))


@pytest.mark.asyncio
async def test_survival_percent_buffs_are_clamped(temp_db):
    uid = 9202
    await character.create(uid, "hpcap")
    await character.create_item_instance(uid, "聚灵佩", affixes={"hp_pct": 0.20})
    inst = (await character.item_instances(uid))[0]
    await character.equip_instance(uid, inst["id"])
    state = {"buffs": {"test": {"until": 9_999_999_999, "effects": {"hp_pct": 0.20}}}}
    await db.execute(
        "UPDATE characters SET debuff_json=? WHERE user_id=?",
        (json.dumps(state, ensure_ascii=False), uid))

    st = await character.stats(await character.get_at(uid, now=1000))
    raw = R.base_stats(0, 0)["hp"]

    assert st["hp"] == int(raw * (1 + BUFFS.SURVIVAL_PCT_CAP))


@pytest.mark.asyncio
async def test_pvp_does_not_halve_pill_buffs(temp_db):
    # 临时 buff（丹药）在 PvP 不折半（spec §6.3 只折半道途/飞升/据点）。
    uid = 9203
    await character.create(uid, "pvptemp")
    await character.add_item(uid, "虎力丹", 1)
    await items.use(uid, "虎力丹")
    char = await character.get_at(uid, now=1000)

    normal = await character.stats(char)
    pvp = await character.stats(char, pvp=True)
    raw = R.base_stats(0, 0)["atk"] + 5

    assert normal["atk"] == int(raw * 1.10)
    assert pvp["atk"] == int(raw * 1.10)


@pytest.mark.asyncio
async def test_pvp_halves_dao_path_percent(temp_db):
    # 道途加成在 PvP 折半。
    dao_uid, ctrl_uid = 9213, 9223
    await character.create(dao_uid, "pvpdao")
    await character.set_progress(dao_uid, 3, 0, 0)
    await dao_path.unlock(dao_uid, "sword")   # 剑修入门 atk_pct=0.03
    await character.create(ctrl_uid, "pvpctrl")
    await character.set_progress(ctrl_uid, 3, 0, 0)

    raw = (await character.stats(await character.get(ctrl_uid)))["atk"]
    dao_char = await character.get(dao_uid)
    normal = await character.stats(dao_char)
    pvp = await character.stats(dao_char, pvp=True)

    assert normal["atk"] == int(raw * 1.03)
    assert pvp["atk"] == int(raw * 1.015)   # 道途部分 ×0.5


@pytest.mark.asyncio
async def test_seclusion_percent_buffs_are_clamped(temp_db):
    uid = 9204
    await character.create(uid, "seclusioncap")
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    state = {"buffs": {"test": {"until": 9_999_999_999, "effects": {"seclusion_pct": 1.0}}}}
    await db.execute(
        "UPDATE characters SET debuff_json=? WHERE user_id=?",
        (json.dumps(state, ensure_ascii=False), uid))

    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=4600)

    assert res["gained"] == settle.seclusion_gain(
        0, 0, 1000, 4600, root_bone=0, place_factor=1 + BUFFS.SECLUSION_PCT_CAP)
    assert res["seclusion_cap_reached"] is True


@pytest.mark.asyncio
async def test_daoxin_tongming_seclusion_buff_enters_clamp(temp_db):
    uid = 9205
    await character.create(uid, "daoxincap")
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    state = {
        "buffs": {
            EVENT_CFG.HEART_TRIBULATION_BUFF_KEY: {
                "until": 9_999_999_999,
                "effects": {"seclusion_pct": EVENT_CFG.HEART_TRIBULATION_SECLUSION_PCT},
            },
            "test": {"until": 9_999_999_999, "effects": {"seclusion_pct": 1.0}},
        }
    }
    await db.execute(
        "UPDATE characters SET debuff_json=? WHERE user_id=?",
        (json.dumps(state, ensure_ascii=False), uid))

    await character.start_seclusion(uid, now=1000)
    res = await character.collect_seclusion(uid, now=4600)

    assert res["gained"] == settle.seclusion_gain(
        0, 0, 1000, 4600, root_bone=0, place_factor=1 + BUFFS.SECLUSION_PCT_CAP)
    assert res["seclusion_cap_reached"] is True


@pytest.mark.asyncio
async def test_disciple_seclusion_bonus_enters_clamp_and_pending_does_not(temp_db):
    active_uid = 9214
    pending_uid = 9215
    await _备好师徒(9314, active_uid, now=1000, confirm=True)
    await _备好师徒(9315, pending_uid, now=1000, confirm=False)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id IN (?,?)",
                     (active_uid, pending_uid))

    await character.start_seclusion(active_uid, now=2000)
    active = await character.collect_seclusion(active_uid, now=5600)
    await character.start_seclusion(pending_uid, now=2000)
    pending = await character.collect_seclusion(pending_uid, now=5600)

    assert active["gained"] == settle.seclusion_gain(
        0, 0, 2000, 5600, root_bone=0,
        place_factor=1 + BONDS_CFG.DISCIPLE_SECLUSION_PCT)
    assert active["disciple_seclusion_pct"] == BONDS_CFG.DISCIPLE_SECLUSION_PCT
    assert active["seclusion_cap_reached"] is False
    assert pending["gained"] == settle.seclusion_gain(0, 0, 2000, 5600, root_bone=0)
    assert pending["disciple_seclusion_pct"] == 0.0


@pytest.mark.asyncio
async def test_disciple_seclusion_bonus_clamps_and_collect_text_is_clear(temp_db):
    from handlers import cultivate as cultivate_handler

    uid = 9216
    await _备好师徒(9316, uid, now=1000, confirm=True)
    await db.execute("UPDATE characters SET root_bone=0 WHERE user_id=?", (uid,))
    state = {"buffs": {"test": {"until": 9_999_999_999, "effects": {"seclusion_pct": 1.0}}}}
    await db.execute(
        "UPDATE characters SET debuff_json=? WHERE user_id=?",
        (json.dumps(state, ensure_ascii=False), uid))

    await character.start_seclusion(uid, now=2000)
    res = await character.collect_seclusion(uid, now=5600)
    text = cultivate_handler._collect_text(res)

    assert res["gained"] == settle.seclusion_gain(
        0, 0, 2000, 5600, root_bone=0, place_factor=1 + BUFFS.SECLUSION_PCT_CAP)
    assert res["seclusion_cap_reached"] is True
    assert "已达闭关增益上限" in text


@pytest.mark.asyncio
async def test_auto_seclusion_uses_disciple_bonus(temp_db):
    uid = 9217
    await _备好师徒(9317, uid, now=1000, confirm=True)
    await db.execute("UPDATE characters SET root_bone=0, cultivation=0 WHERE user_id=?", (uid,))
    await db.execute("UPDATE users SET last_seen_at=? WHERE tg_user_id=?", (1000, uid))

    res = await character.touch_activity(uid, "传承弟子9217", now=8200)
    char = await character.get(uid)

    assert res["status"] == "ok"
    assert res["auto_cultivation"] == settle.seclusion_gain(
        0, 0, 4600, 8200, root_bone=0,
        place_factor=1 + BONDS_CFG.DISCIPLE_SECLUSION_PCT)
    assert char.cultivation == res["auto_cultivation"]
