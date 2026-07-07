"""长线 sink 回归测试(#13):法宝强化/重铸/分解、宗门捐输、秘境入场费。"""
import pytest
import pytest_asyncio

from config import equipment as EQ
from config.dungeons import DUNGEONS
from config.sects import DONATE_DAILY_CONTRIBUTION_CAP as CAP
from config.sects import DONATE_STONE_PER_CONTRIBUTION as PER
from models import db
from services import character, dungeon, equipment, sect


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "sinks-test.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _first_instance(uid, base_key=None):
    rows = await character.item_instances(uid)
    if base_key:
        rows = [r for r in rows if r["base_key"] == base_key]
    return rows[0]["id"]


@pytest.mark.asyncio
async def test_enhance_raises_stats_costs_rise_and_caps(temp_db):
    uid = 6001
    await character.create(uid, "smith")
    await character.set_progress(uid, 2, 0, 0)
    await character.add_stone(uid, 1_000_000)
    await character.add_item(uid, EQ.QIHUN_KEY, 999)
    await character.create_item_instance(uid, "玄铁剑")        # atk+38（灵阶武器）
    iid = await _first_instance(uid)
    await character.equip_instance(uid, iid)

    base_atk = (await character.stats(await character.get(uid)))["atk"]
    res = await equipment.enhance(uid, iid)
    assert res["status"] == "ok" and res["level"] == 1
    assert (await character.stats(await character.get(uid)))["atk"] > base_atk

    assert EQ.enhance_cost(1)["stone"] > EQ.enhance_cost(0)["stone"]   # 成本递增

    res = {"status": "ok"}
    for _ in range(30):
        res = await equipment.enhance(uid, iid)
        if res["status"] == "max":
            break
    assert res["status"] == "max" and res["level"] == EQ.ENHANCE_MAX_LEVEL


def test_enhanced_equipment_bonus_scales_flat_stats_only():
    """强化后显示增益只放大平加属性，不放大百分比词条与战斗修正。"""
    inst = {
        "base_key": "玄铁剑",
        "enhance_level": 2,
        "affixes": {"atk": 10, "atk_pct": 0.05, "pierce": 3},
    }

    bonus = character.enhanced_equipment_bonus(inst)

    assert bonus["atk"] == int(round((38 + 10) * (1 + 2 * EQ.ENHANCE_PER_LEVEL)))
    assert bonus["crit"] == int(round(4 * (1 + 2 * EQ.ENHANCE_PER_LEVEL)))
    assert bonus["atk_pct"] == 0.05
    assert bonus["pierce"] == 3


@pytest.mark.asyncio
async def test_enhance_requires_qihun(temp_db):
    uid = 6002
    await character.create(uid, "poor")
    await character.set_progress(uid, 2, 0, 0)
    await character.add_stone(uid, 1_000_000)                  # 有灵石、无器魂
    await character.create_item_instance(uid, "玄铁剑")
    res = await equipment.enhance(uid, await _first_instance(uid))
    assert res["status"] == "no_material"


@pytest.mark.asyncio
async def test_reforge_rerolls_affixes_and_charges(temp_db):
    uid = 6003
    await character.create(uid, "reforger")
    await character.set_progress(uid, 2, 0, 0)
    await character.add_stone(uid, 10_000)
    await character.add_item(uid, EQ.QIHUN_KEY, 50)
    await character.create_item_instance(uid, "玄铁剑", affixes={"atk_pct": 0.05})
    iid = await _first_instance(uid)

    before = (await character.get(uid)).spirit_stone
    res = await equipment.reforge(uid, iid)
    assert res["status"] == "ok" and "affixes" in res
    assert (await character.get(uid)).spirit_stone < before


@pytest.mark.asyncio
async def test_decompose_yields_qihun_and_refuses_equipped(temp_db):
    uid = 6004
    await character.create(uid, "breaker")
    await character.set_progress(uid, 2, 0, 0)
    await character.create_item_instance(uid, "聚灵佩")        # 宝阶，装备后不可分解
    pendant = await _first_instance(uid, "聚灵佩")
    await character.equip_instance(uid, pendant)
    assert (await equipment.decompose(uid, pendant))["status"] == "equipped"

    await character.create_item_instance(uid, "玄铁剑")        # 灵阶，未装备
    sword = await _first_instance(uid, "玄铁剑")
    res = await equipment.decompose(uid, sword)
    assert res["status"] == "ok" and res["qihun"] == EQ.DECOMPOSE_QIHUN["灵"]
    assert await character.item_qty(uid, EQ.QIHUN_KEY) == EQ.DECOMPOSE_QIHUN["灵"]


@pytest.mark.asyncio
async def test_sect_donate_converts_stone_with_daily_cap(temp_db):
    uid = 6005
    await character.create(uid, "donor")
    await character.set_progress(uid, 1, 0, 0)
    await character.add_stone(uid, 100_000)
    await sect.create(uid, "捐输宗", now=1000)

    before = (await character.get(uid)).spirit_stone
    res = await sect.donate(uid, PER * (CAP + 20), now=1000)   # 超过当日上限
    assert res["status"] == "ok" and res["contribution"] == CAP
    assert (await character.get(uid)).spirit_stone == before - PER * CAP
    assert (await sect.donate(uid, PER * 5, now=1000))["status"] == "donate_cap"
    assert (await sect.donate(uid, PER * 5, now=1000 + 86400))["status"] == "ok"


@pytest.mark.asyncio
async def test_dungeon_entry_fee_blocks_and_charges(temp_db):
    uid = 6006
    await character.create(uid, "delver")
    await character.set_progress(uid, 2, 0, 0)
    await db.execute(
        "UPDATE characters SET stamina=?, stamina_at=? WHERE user_id=?", (200, 1000, uid))
    fee = DUNGEONS["qingyun"]["entry_stone"]

    assert (await dungeon.start(uid, "qingyun", now=1000))["status"] == "no_entry_fee"
    await character.add_stone(uid, fee + 100)
    before = (await character.get(uid)).spirit_stone
    res = await dungeon.start(uid, "qingyun", now=1000)
    assert res["status"] == "started" and res["entry_fee"] == fee
    assert (await character.get(uid)).spirit_stone == before - fee
