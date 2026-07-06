"""V2 审计修复回归（docs/plans/v2/audit.md）。

覆盖：A1 据点掉率合算、A4 丹修/器修真实生效、B3 化神丹残方配方、
     C3 need_pill 来源指引 / 飞升播报 + 尊号。
"""
import random

import pytest
import pytest_asyncio

from config import ascension as ASC
from config import realms as R
from config import recipes as REC
from config import shop as SHOP
from config.items import ITEMS
from models import db
from services import (ascension, breakthrough, character, crafting, dao_path, items,
                      sect_war)


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "audit.db"))
    try:
        yield
    finally:
        await db.close_db()


# ---- A1：据点 drop_pct 合算进掉率 ----

def test_total_drop_pct_includes_outpost():
    assert sect_war.total_drop_pct(0.0, {"drop_pct": 0.05}) == 0.05
    assert sect_war.total_drop_pct(0.10, {"drop_pct": 0.05}) == pytest.approx(0.15)
    assert sect_war.total_drop_pct(0.18, {"drop_pct": 0.05}) == 0.20   # 封顶 +20%
    assert sect_war.total_drop_pct(0.0, {}) == 0.0


# ---- A4 器修：forge_pct 放大炼器词条品质 ----

def test_forge_quality_scales_affixes():
    base = crafting._roll_affixes("陨星剑", 50, 5, rng=random.Random(7), quality_mult=1.0)
    boosted = crafting._roll_affixes("陨星剑", 50, 5, rng=random.Random(7), quality_mult=1.10)

    assert set(base) == set(boosted)
    assert all(boosted[k] >= base[k] for k in base)
    assert any(boosted[k] > base[k] for k in base)


# ---- A4 丹修：alchemy_pct 提升真实突破成功率 ----

@pytest.mark.asyncio
async def test_alchemy_path_raises_real_breakthrough_rate(temp_db, monkeypatch):
    # base_rate=0.50；丹修宗师 alchemy_pct=0.10 → 0.60。random 固定 0.55：
    # 有丹修 → 成功（进神魂劫）；无丹修 → 失败。证明 alchemy_pct 真实接入突破。
    async def setup(uid: str) -> int:
        await character.create(uid, "alc")
        await character.set_progress(uid, 3, 3, R.advance_cost(3, 3))
        await db.execute("UPDATE characters SET root_bone=50 WHERE user_id=?", (uid,))
        await character.add_item(uid, "化神丹", 1)
        return uid

    dao_uid, ctrl_uid = 7001, 7002
    await setup(dao_uid)
    await setup(ctrl_uid)
    await dao_path.unlock(dao_uid, "alchemy")
    await db.execute(
        "UPDATE dao_paths SET rank=4 WHERE user_id=? AND path_key='alchemy'", (dao_uid,))

    monkeypatch.setattr(random, "random", lambda: 0.55)
    dao_res = await breakthrough.try_advance(dao_uid)
    ctrl_res = await breakthrough.try_advance(ctrl_uid)

    assert dao_res["status"] == "tribulation_choice"   # 丹修加成把 0.55 拉进成功区
    assert ctrl_res["status"] == "big_fail"            # 无加成则失败


# ---- B3：残方→化神丹配方打通获取链 ----

@pytest.mark.asyncio
async def test_huashen_pill_recipe_converts_scraps(temp_db):
    assert "化神丹" not in SHOP.SHOP_ITEMS          # 维持反套利：不进 NPC 直售
    assert ITEMS["化神丹方"]["recipe"] == "huashen_pill"
    assert REC.RECIPES["huashen_pill"]["realm"] == 3

    uid = 7003
    await character.create(uid, "danxiu")
    last_yuanying = R.num_stages(3) - 1
    await character.set_progress(uid, 3, last_yuanying, R.advance_cost(3, last_yuanying))
    await character.add_stone(uid, 5000)
    await character.add_item(uid, "化神丹残方", 8)
    await character.add_item(uid, "妖丹", 4)
    await character.add_item(uid, "化神丹方", 1)

    learn = await items.use(uid, "化神丹方")
    assert learn["status"] in ("recipe_ok", "known_recipe")

    started = await crafting.start_job(uid, "huashen_pill", now=1000)
    assert started["status"] == "started"
    collected = await crafting.collect_ready(uid, now=1000 + started["seconds"])

    assert any(c["name"] == "化神丹" for c in collected)
    assert await character.item_qty(uid, "化神丹") == 1
    assert await character.item_qty(uid, "化神丹残方") == 2   # 8 张残方炼丹消耗 6 张


# ---- C3：need_pill 化神丹来源指引（spec T0.8）----

def test_need_pill_huashen_hints_source():
    from handlers import cultivate
    huashen = cultivate._bt_text({"status": "need_pill", "pill": "化神丹"})
    yuanjing = cultivate._bt_text({"status": "need_pill", "pill": "元婴丹"})

    assert "天外古墟" in huashen                       # 给出化神丹出处
    assert "化神丹残方" in huashen or "太虚天门" in huashen   # 或炼丹链路
    assert "天外古墟" not in yuanjing                 # 非化神丹不给误导指引


# ---- C3：飞升尊号派生 + 试炼/被动升级群播报（spec T3.5）----

def test_ascension_title_thresholds():
    assert ASC.ascension_title(0) == ""
    assert ASC.ascension_title(1) == "飞升新秀"
    assert ASC.ascension_title(3) == "飞升真君"
    assert ASC.ascension_title(5) == "渡劫仙尊"


async def _join_group(uid: int, chat_id: int):
    """让玩家挂到一个群，使群播报能落库（social 依赖 bot_chat_members）。"""
    await db.execute(
        "INSERT INTO bot_chat_members(chat_id, user_id, last_seen_at) VALUES(?,?,?)",
        (chat_id, uid, 1000))


@pytest.mark.asyncio
async def test_ascension_upgrade_broadcasts_with_title(temp_db):
    uid = 7010
    await character.create(uid, "feisheng")
    await _join_group(uid, -1007010)
    async with db.transaction() as conn:
        await ascension.add_points_conn(conn, uid, 1, now=1000)

    res = await ascension.upgrade_passive(uid, "hp_pct", now=1000)

    assert res["status"] == "ok"
    assert res["title"] == "飞升新秀"               # level 0→1 解锁首档尊号
    rows = await db.fetchall(
        "SELECT text FROM social_broadcasts WHERE user_id=? AND event_type='ascension.upgrade'",
        (uid,))
    assert rows, "ascension.upgrade 应触发群播报"
    assert any("尊号" in r["text"] and "飞升新秀" in r["text"] for r in rows)


@pytest.mark.asyncio
async def test_ascension_trial_broadcasts(temp_db):
    uid = 7011
    await character.create(uid, "trial-bc")
    await character.set_progress(uid, 4, 3, R.advance_cost(4, 3))
    await db.execute(
        "UPDATE characters SET daohang=? WHERE user_id=?",
        (ASC.TRIAL_DAOHANG_COST + 100, uid))
    await _join_group(uid, -1007011)

    res = await ascension.trial(uid, now=1000)

    assert res["status"] == "ok"
    rows = await db.fetchall(
        "SELECT text FROM social_broadcasts WHERE user_id=? AND event_type='ascension.trial'",
        (uid,))
    assert rows, "ascension.trial 应触发群播报"
    assert any("飞升试炼" in r["text"] for r in rows)
