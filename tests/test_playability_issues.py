import pytest
import pytest_asyncio

from bot.presentation import plain_text
from models import db
from services import character, explore, game_events, quests, social, world_boss


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "playability.db"))
    try:
        yield
    finally:
        await db.close_db()


class StableRng:
    def random(self):
        return 1.0

    def randint(self, low, high):
        return low

    def choice(self, values):
        return values[0]


class EncounterRng(StableRng):
    def __init__(self):
        self.values = [1.0, 0.0]

    def random(self):
        if self.values:
            return self.values.pop(0)
        return 1.0


@pytest.mark.asyncio
async def test_sweep_unlocks_after_stable_clears_and_records_focus_window(temp_db):
    uid = 8001
    await character.create(uid, "sweeper")
    await db.execute(
        "INSERT INTO explore_mastery(user_id, map_key, consecutive_wins, last_result_at) "
        "VALUES(?,?,?,?)",
        (uid, "后山", explore.SWEEP_UNLOCK_WINS, 1000))

    res = await explore.sweep(uid, "后山", now=2000, rng=StableRng())
    char = await character.get_at(uid, now=2000)
    windows = await db.fetchall(
        "SELECT kind, source_key FROM activity_windows WHERE user_id=?",
        (uid,))

    assert res["status"] == "ok"
    assert res["sweep"] is True
    assert char.stamina == 90
    assert await explore.active_run(uid, now=2000) is None
    assert any(row["kind"] == "sweep" and row["source_key"] == "后山" for row in windows)


@pytest.mark.asyncio
async def test_explore_encounter_waits_for_choice_then_resolves_once(temp_db):
    uid = 8002
    await character.create(uid, "wanderer")

    started = await explore.start(uid, "后山", now=1000, rng=EncounterRng())
    pending = await explore.collect(uid, now=started["finish_at"], rng=StableRng())
    done = await explore.choose_event(uid, "probe", now=started["finish_at"], rng=StableRng())
    second = await explore.collect(uid, now=started["finish_at"], rng=StableRng())

    assert started["event"] == "cliff_cave"
    assert pending["status"] == "event"
    assert {c["key"] for c in pending["choices"]} == {"probe", "detour", "rescue"}
    assert done["status"] == "ok"
    assert any("洞府" in line for line in done["log"])
    assert second["status"] == "no_active"


@pytest.mark.asyncio
async def test_quest_progress_claim_and_achievement_reward(temp_db):
    uid = 8003
    await character.create(uid, "quester")
    before = (await character.get(uid)).spirit_stone

    async with db.transaction() as conn:
        for _ in range(3):
            await game_events.emit_conn(conn, uid, "explore.win", {"amount": 1}, now=1000)

    state = await quests.list_status(uid, now=1000)
    daily = next(q for q in state["quests"] if q["key"] == "daily_explore")
    claimed = await quests.claim(uid, "daily_explore", now=1000)
    after = (await character.get(uid)).spirit_stone

    assert daily["ready"] is True
    assert claimed["status"] == "ok"
    assert after == before + 120


@pytest.mark.asyncio
async def test_achievements_are_visible_on_me_panel(temp_db):
    from handlers import me as me_handler

    uid = 8005
    await character.create(uid, "achiever")
    async with db.transaction() as conn:
        await game_events.emit_conn(
            conn, uid, "explore.boss_win",
            {"mob": "千年青牛", "amount": 1}, now=1000)

    content, _ = await me_handler.render_me(uid)
    text = plain_text(content)

    assert "🏅 成就：初斩妖王" in text


@pytest.mark.asyncio
async def test_me_panel_uses_equipped_weapon_instance(temp_db):
    from handlers import me as me_handler

    uid = 8007
    await character.create(uid, "bluepants")
    await character.create_item_instance(uid, "玄铁剑")
    inst = (await character.item_instances(uid))[0]

    assert (await character.equip_instance(uid, inst["id"]))["status"] == "ok"
    assert (await character.get(uid)).weapon_key == "新手剑"

    content, _ = await me_handler.render_me(uid)
    text = plain_text(content)

    assert "⚔️ 法宝：玄铁剑" in text
    assert "⚔️ 法宝：新手木剑" not in text


@pytest.mark.asyncio
async def test_me_panel_uses_same_weapon_predicate_as_stats(temp_db):
    from handlers import me as me_handler

    uid = 8008
    await character.create(uid, "drifter")
    await character.create_item_instance(uid, "玄铁剑")
    inst = (await character.item_instances(uid))[0]
    await db.execute(
        "UPDATE item_instances SET equipped_slot='armor' WHERE id=?",
        (inst["id"],))

    content, _ = await me_handler.render_me(uid)
    text = plain_text(content)

    assert "⚔️ 法宝：玄铁剑" in text
    assert "⚔️ 法宝：新手木剑" not in text


@pytest.mark.asyncio
async def test_social_broadcasts_and_rank_notifications_are_queued_and_flushed(temp_db):
    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, target, text):
            self.sent.append((target, text))

    uid = 8004
    chat_id = -88004
    await character.create(uid, "socialite")
    await world_boss.remember_chat(chat_id, "试炼群", now=1000)
    await world_boss.remember_cultivator(chat_id, uid, now=1000)

    async with db.transaction() as conn:
        await game_events.emit_conn(
            conn, uid, "explore.boss_win",
            {"mob": "千年青牛", "amount": 1}, now=1000)
        await social.queue_rank_change_conn(conn, uid, 990, 1210, None, 9, now=1000)

    pending = await db.fetchall(
        "SELECT chat_id, user_id, text FROM social_broadcasts WHERE status='pending'",
        ())
    bot = FakeBot()
    flushed = await social.flush_broadcasts(bot, now=1000)

    assert len(pending) >= 3
    assert any(row["chat_id"] == chat_id and "妖王" in row["text"] for row in pending)
    assert any(row["chat_id"] is None and row["user_id"] == uid for row in pending)
    assert flushed["sent"] == len(bot.sent) == len(pending)


@pytest.mark.asyncio
async def test_tribulation_preserves_cultivation_gained_midway(temp_db, monkeypatch):
    """渡劫挂起期间并行获得的修为，结算时必须保留（不被建场快照覆盖）。"""
    from config import realms as R
    from services import breakthrough

    uid = 8006
    await character.create(uid, "tribber")
    last_zj = R.num_stages(1) - 1
    cost = R.advance_cost(1, last_zj)
    await character.set_progress(uid, 1, last_zj, cost)
    await character.add_item(uid, "金丹", 1)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)  # 渡劫概率必过

    start = await breakthrough.try_advance(uid)
    assert start["status"] == "tribulation_choice"

    # 渡劫挂起期间，并行历练奖励给修为（A1 允许历练与渡劫并行）。
    gained = 777
    async with db.transaction() as conn:
        await character._grant_reward_conn(conn, uid, 0, gained, None)

    for _ in range(3):
        res = await breakthrough.choose_tribulation_action(uid, "artifact")
    assert res["status"] == "big_success"

    # 期望 = 中途修为(cost+gained) - cost = gained；旧 bug 会写回快照-cost=0，丢掉 gained。
    char = await character.get(uid)
    assert char.cultivation == gained


@pytest.mark.asyncio
async def test_game_event_failure_does_not_roll_back_core_action(temp_db, monkeypatch):
    """事件副作用（任务/播报）抛异常时，只回滚事件写入，核心动作照常提交。"""
    uid = 8007
    await character.create(uid, "robust")
    before = (await character.get(uid)).spirit_stone

    async def boom(*args, **kwargs):
        raise RuntimeError("quest plumbing exploded")
    monkeypatch.setattr(quests, "record_event_conn", boom)

    async with db.transaction() as conn:
        await character._grant_reward_conn(conn, uid, 500, 0, None)  # 核心动作
        await game_events.emit_conn(conn, uid, "explore.win", {"amount": 1}, now=1000)

    # 核心动作（+500 灵石）已提交；事件 savepoint 回滚后无任务进度、未抛异常。
    assert (await character.get(uid)).spirit_stone == before + 500
    progress = await db.fetchall(
        "SELECT 1 FROM quest_progress WHERE user_id=?", (uid,))
    assert progress == []

@pytest.mark.asyncio
async def test_new_v2_handlers_render_without_missing_daohang(temp_db):
    from handlers import ascension as ascension_handler
    from handlers import dao_path as path_handler

    uid = 8009
    await character.create(uid, "v2ui")
    await db.execute("UPDATE characters SET daohang=? WHERE user_id=?", (123, uid))

    path_text, path_markup = await path_handler.render_path(uid)
    asc_text, asc_markup = await ascension_handler.render_ascension(uid)

    assert "道行：123" in path_text
    assert "道行：123" in asc_text
    assert path_markup is not None
    assert asc_markup is not None


def test_shenhun_fail_text_uses_shenhun_label():
    from handlers.cultivate import _bt_text

    text = _bt_text({
        "status": "big_fail",
        "tribulation": True,
        "loss": 100,
        "tribulation_log": ["第 1 道神魂劫落下，承伤 999，余气血 0/100"],
    })

    assert "神魂劫凶险" in text
    assert "天劫凶猛" not in text
