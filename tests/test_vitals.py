"""气血/法力资源化回归（#24）：自然回复、当前值结算/clamp、活动写回、丹药上限。"""
import pytest
import pytest_asyncio

from bot.presentation import plain_text
from handlers import common
from models import db
from services import character, items, settle
from services import explore as explore_service

DAY = 24 * 3600


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "vitals-test.db"))
    try:
        yield
    finally:
        await db.close_db()


# ---- 纯函数：回复结算 ----

def test_regen_resource_scales_and_caps():
    # spf=2000 ⇒ 0→满 2000s；1000s 恰半。
    assert settle.regen_resource(0, 1000, 0, 1000, 2000) == (500, 1000)
    # 满则封顶、锚点归 now。
    assert settle.regen_resource(900, 1000, 0, 99999, 2000) == (1000, 99999)
    # 已满直接返回。
    assert settle.regen_resource(1000, 1000, 123, 99999, 2000) == (1000, 99999)


def test_regen_resource_carries_remainder_on_rapid_reads():
    # cap=100, spf=2000 ⇒ 20s / 点。
    assert settle.regen_resource(0, 100, 0, 10, 2000) == (0, 0)     # 不足一点：不回、锚点不动
    val, at = settle.regen_resource(0, 100, 0, 25, 2000)
    assert val == 1 and at == 20                                    # 回1点；锚点只前移20s，5s零头留存


# ---- vitals：NULL=满 / clamp / 离线回复 ----

@pytest.mark.asyncio
async def test_vitals_null_is_full_then_clamp_and_regen(temp_db):
    uid = 7002
    await character.create(uid, "tester")
    st = await character.stats(await character.get(uid))

    # NULL ⇒ 视为满。
    v = await character.vitals(await character.get(uid), now=1000)
    assert v["hp"] == st["hp"] and v["mp"] == st["mp"]
    assert v["max_hp"] == st["hp"] and v["max_mp"] == st["mp"]

    # 残血后离线回复（10 分钟：HP +3%/分、MP +6%/分）。
    await db.execute(
        "UPDATE characters SET current_hp=1, current_mp=1, hp_at=1000, mp_at=1000 WHERE user_id=?",
        (uid,))
    v = await character.vitals(await character.get(uid), now=1000 + 600)
    assert 1 < v["hp"] <= st["hp"]
    assert 1 < v["mp"] <= st["mp"]

    # 当前值超过 max（换装/降境致 max 下降）时 clamp 回 max。
    await db.execute(
        "UPDATE characters SET current_hp=999999, hp_at=? WHERE user_id=?", (1000 + 600, uid))
    v = await character.vitals(await character.get(uid), now=1000 + 600)
    assert v["hp"] == st["hp"]


@pytest.mark.asyncio
async def test_vitals_offline_regen_persists(temp_db):
    uid = 7004
    await character.create(uid, "tester")
    await db.execute(
        "UPDATE characters SET current_hp=1, current_mp=1, hp_at=1000, mp_at=1000 WHERE user_id=?",
        (uid,))
    await character.vitals(await character.get(uid), now=1000 + 600)
    row = await db.fetchone(
        "SELECT current_hp, current_mp, hp_at FROM characters WHERE user_id=?", (uid,))
    assert row["current_hp"] > 1 and row["current_mp"] > 1   # 已落库


# ---- 活动写回：胜负都不破 20% 地板、不超 max ----

@pytest.mark.asyncio
async def test_explore_writes_back_vitals_within_floor(temp_db):
    uid = 7001
    await character.create(uid, "tester")
    started = await explore_service.start(uid, "后山", now=1000)
    res = await explore_service.collect(uid, now=started["finish_at"])

    assert res["status"] == "ok"
    floor = int(res["max_hp"] * settle.HP_FLOOR_PCT)
    assert res["battle_hp_before"] == res["max_hp"]   # 首次出战满血（NULL=满）
    assert floor <= res["hp_after"] <= res["max_hp"]  # 写回不破地板、不超上限
    assert 0 <= res["mp_after"] <= res["max_mp"]
    row = await db.fetchone(
        "SELECT current_hp, current_mp FROM characters WHERE user_id=?", (uid,))
    assert row["current_hp"] == res["hp_after"]
    assert row["current_mp"] == res["mp_after"]


# ---- 丹药：回血/回蓝/补满，均受上限封顶 ----

@pytest.mark.asyncio
async def test_full_restore_pill_caps_at_max(temp_db):
    uid = 7003
    await character.create(uid, "tester")
    st = await character.stats(await character.get(uid))
    await db.execute(
        "UPDATE characters SET current_hp=1, current_mp=1, hp_at=1000, mp_at=1000 WHERE user_id=?",
        (uid,))
    await character.add_item(uid, "大还丹", 2)

    res = await items.use(uid, "大还丹", now=1000)
    assert res["status"] == "vital_restored"
    assert res["hp"] == st["hp"] and res["mp"] == st["mp"]   # 补满，不溢出
    # 已满再服 → 提示无需。
    assert (await items.use(uid, "大还丹", now=1000))["status"] == "vital_full"


# ---- P1：战斗按「出发时」状态结算，不被晚领/中途嗑丹绕过 ----

@pytest.mark.asyncio
async def test_late_collect_regenerates_from_combat_result(temp_db):
    uid = 7005
    await character.create(uid, "tester")
    st = await character.stats(await character.get(uid))
    started = await explore_service.start(uid, "后山", now=1000)
    # 很晚领取：从「战斗结束状态」(finish_at) 自然回复到 now，应回满；
    # 而非把战斗损耗从「已回满的当前」里再扣一遍（#24 P1 事件顺序）。
    res = await explore_service.collect(uid, now=started["finish_at"] + 10**7)
    assert res["status"] == "ok"
    assert res["hp_after"] >= st["hp"] - 2
    assert res["mp_after"] >= st["mp"] - 2


# ---- P3：疗伤丹按「清 debuff 后」的真实 max 回血 ----

@pytest.mark.asyncio
async def test_heal_pill_heals_against_post_clear_max(temp_db):
    uid = 7006
    await character.create(uid, "tester")
    st = await character.stats(await character.get(uid))   # 真实 max（无 debuff）
    eff_max = max(1, int(st["hp"] * 0.9))                  # 道基不稳压制后的 max
    # 满血（受压制）+ 道基不稳（远未来时间戳，确保 stats 真的施加 -10%）。
    await db.execute(
        "UPDATE characters SET current_hp=?, current_mp=?, hp_at=1000, mp_at=1000, "
        "debuff_json=? WHERE user_id=?",
        (eff_max, st["mp"], '{"unstable_until": 9999999999}', uid))
    await character.add_item(uid, "疗伤丹", 1)
    res = await items.use(uid, "疗伤丹", now=1000)

    assert res["status"] == "vital_restored" and res["cleared_unstable"] is True
    assert res["max_hp"] == st["hp"]      # 按清 debuff 后的真实 max（非被压制的 90%）
    assert res["hp"] == st["hp"]          # 满血保持满，而非 180/200


# ---- P2：低法力提示与结算断档反馈 ----

def test_low_mp_warning_and_starved_note():
    line = common.vitals_line({"hp": 100, "max_hp": 100, "mp": 5, "max_mp": 100})
    assert "法力不足" in line and "气血不足" not in line
    assert common.mp_starved_note({"max_mp": 100, "battle_mp_before": 90, "battle_mp_after": 10}) != ""
    assert common.mp_starved_note({"max_mp": 100, "battle_mp_before": 90, "battle_mp_after": 90}) == ""


def test_explore_timeout_loss_text_explains_remaining_hp():
    from handlers import explore as explore_handler
    from services.combat import round_limit_label

    content = explore_handler._result_text({
        "status": "ok",
        "map_key": "后山",
        "map": "青牛后山",
        "win": False,
        "is_boss": False,
        "defeat_reason": "round_limit",
        "log": [
            "第 1 战：遭遇 天魔残兵",
            f"🏆 天魔残兵 胜！（{round_limit_label()}未分胜负，按剩余气血比例判定）",
        ],
        "reward": {"stone": 0, "cult": 0, "drops": {}},
        "stamina_left": 100,
        "battle_hp_before": 7879,
        "battle_hp_after": 4678,
        "battle_mp_before": 911,
        "battle_mp_after": 911,
        "hp_after": 4827,
        "mp_after": 911,
        "max_hp": 7879,
        "max_mp": 911,
    })
    text = plain_text(content)

    assert f"久战 {round_limit_label()}未决" in text
    assert "气血 7879→4678/7879" in text


# ---- P2：结算区分「本场战斗快照」与「领取后当前状态」 ----

@pytest.mark.asyncio
async def test_settlement_separates_battle_and_current(temp_db):
    uid = 7008
    await character.create(uid, "tester")
    # 近空血出发 → 必败；战斗末≈0，但当前受 20% 重伤地板保护。
    await db.execute(
        "UPDATE characters SET current_hp=1, current_mp=1, hp_at=2000, mp_at=2000 WHERE user_id=?",
        (uid,))
    started = await explore_service.start(uid, "后山", now=2000)
    res = await explore_service.collect(uid, now=started["finish_at"])

    assert res["status"] == "ok" and res["win"] is False
    # 战斗反馈反映「出发残血→战斗末」，而非领取时状态（不掩盖低血出门的败因）。
    assert res["battle_hp_before"] == 1 and res["battle_hp_after"] == 0
    # 当前（落库）受重伤地板保护，与战斗末不同 → 展示两行。
    assert res["hp_after"] >= int(res["max_hp"] * settle.HP_FLOOR_PCT)
    assert len(common.battle_vitals_lines(res)) >= 2


# ---- P3：活动进行中不可服恢复丹（冻结期间不回血），完成后可用 ----

@pytest.mark.asyncio
async def test_restore_pill_blocked_until_run_collected(temp_db):
    uid = 7007
    await character.create(uid, "tester")
    await character.add_item(uid, "大还丹", 1)
    started = await explore_service.start(uid, "后山", now=1000)

    # 进行中：拒用、不扣库存。
    assert (await items.use(uid, "大还丹", now=1000))["status"] == "busy_activity"
    # 已完成但未领取：仍拒用（须先领取把战斗结果落库，才能正确叠加丹药）。
    assert (await items.use(uid, "大还丹", now=started["finish_at"]))["status"] == "busy_activity"
    assert await character.item_qty(uid, "大还丹") == 1
    # 领取后可用。
    await explore_service.collect(uid, now=started["finish_at"])
    ok = await items.use(uid, "大还丹", now=started["finish_at"])
    assert ok["status"] in ("vital_restored", "vital_full")
