from __future__ import annotations

import pytest
import pytest_asyncio

from config import auction as auction_cfg
from config import natal as NATAL
from handlers import skills as skills_handler
from handlers.common import action_callback_data
from models import db
from services import character


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "skills-natal-handlers.db"))
    try:
        yield
    finally:
        await db.close_db()


class _User:
    def __init__(self, user_id: int):
        self.id = user_id


class _Chat:
    def __init__(self, chat_type: str = "private"):
        self.type = chat_type


class _Bot:
    async def get_me(self):
        return type("Me", (), {"username": "xian_test_bot"})()


class _Message:
    def __init__(self, user_id: int, text: str = "/skills", chat_type: str = "private"):
        self.from_user = _User(user_id)
        self.text = text
        self.chat = _Chat(chat_type)
        self.bot = _Bot()
        self.answers = []
        self.edits = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class _Callback:
    def __init__(self, user_id: int, data: str, chat_type: str = "private"):
        self.from_user = _User(user_id)
        self.data = data
        self.message = _Message(user_id, chat_type=chat_type)
        self.bot = self.message.bot
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def _datas(markup):
    return [button.callback_data for button in _buttons(markup)]


async def _备好元婴道友(user_id: int):
    await character.create(user_id, f"本命道友{user_id}")
    await character.set_progress(user_id, NATAL.MIN_REALM, 0, 0)


async def _造法宝(user_id: int, key: str = "天魔刃") -> int:
    await character.create_item_instance(user_id, key)
    rows = await character.item_instances(user_id)
    return int(rows[-1]["id"])


async def _给材料(user_id: int, cost: dict):
    await character.add_stone(user_id, int(cost.get("stone", 0)))
    for key, qty in cost.get("items", {}).items():
        await character.add_item(user_id, key, int(qty))


async def _取令牌(callback_data: str) -> dict:
    token = callback_data.rsplit(":", 1)[1]
    row = await db.fetchone(
        "SELECT user_id, action, consumed_at FROM callback_tokens WHERE token=?",
        (token,))
    return dict(row) if row else {}


@pytest.mark.asyncio
async def test_skills_法宝列表只保留换装与单件操作入口(temp_db):
    uid = 9300
    await character.create(uid, f"菜单道友{uid}")
    equipped_id = await _造法宝(uid, "玄铁剑")
    spare_id = await _造法宝(uid, "陨星剑")
    await character.equip_instance(uid, equipped_id)

    _text, markup = await skills_handler.render_skills_category(uid, "equipment")
    datas = _datas(markup)
    token_actions = {
        row["action"]
        for data in datas
        if (row := await _取令牌(data))
    }

    assert {f"skills:item:{equipped_id}", f"skills:item:{spare_id}"} <= set(datas)
    assert token_actions == {f"eq:unequip:{equipped_id}", f"equip:{spare_id}"}


@pytest.mark.asyncio
async def test_skills_单件法宝页承载养成操作(temp_db):
    uid = 9302
    await _备好元婴道友(uid)
    inst_id = await _造法宝(uid, "天魔刃")

    _text, markup = await skills_handler.render_equipment_item(uid, inst_id)
    datas = _datas(markup)
    actions = {
        row["action"]
        for data in datas
        if (row := await _取令牌(data))
    }

    assert "skills:cat:equipment" in datas
    assert actions == {
        f"eq:enhance:{inst_id}",
        f"eq:reforge:{inst_id}",
        f"eq:decompose:{inst_id}",
        f"natal:bind:{inst_id}",
    }


@pytest.mark.asyncio
async def test_skills_不存在的单件法宝页只返回列表(temp_db):
    uid = 9303
    await character.create(uid, f"寻宝道友{uid}")

    _text, markup = await skills_handler.render_equipment_item(uid, 999999)

    assert _datas(markup) == ["skills:cat:equipment"]


@pytest.mark.asyncio
async def test_skills_拍卖托管法宝操作页不提供状态变更(temp_db):
    uid = 9306
    await character.create(uid, f"寄拍道友{uid}")
    inst_id = await _造法宝(uid, "玄铁剑")
    await db.execute(
        "UPDATE item_instances SET status=? WHERE id=?",
        (auction_cfg.INSTANCE_STATUS_AUCTION, inst_id))

    _text, markup = await skills_handler.render_equipment_item(uid, inst_id)

    assert _datas(markup) == ["skills:cat:equipment"]


@pytest.mark.asyncio
async def test_skills_单件法宝回调打开操作页(temp_db):
    uid = 9304
    await character.create(uid, f"炼器道友{uid}")
    inst_id = await _造法宝(uid, "玄铁剑")
    callback = _Callback(uid, f"skills:item:{inst_id}")

    await skills_handler.cb_skills_item(callback)

    assert callback.message.edits
    assert "skills:cat:equipment" in _datas(callback.message.edits[-1][1])
    assert callback.answers == [(None, False)]


@pytest.mark.asyncio
async def test_skills_养成结果返回当前法宝且分解结果返回列表(temp_db):
    uid = 9305
    await character.create(uid, f"百炼道友{uid}")
    enhance_id = await _造法宝(uid, "玄铁剑")
    enhance_data = await action_callback_data(uid, f"eq:enhance:{enhance_id}")
    enhanced = _Callback(uid, enhance_data)

    await skills_handler.cb_enhance(enhanced)

    assert f"skills:item:{enhance_id}" in _datas(enhanced.message.edits[-1][1])
    assert "skills:cat:equipment" in _datas(enhanced.message.edits[-1][1])

    decompose_id = await _造法宝(uid, "陨星剑")
    decompose_data = await action_callback_data(uid, f"eq:decompose:{decompose_id}")
    decomposed = _Callback(uid, decompose_data)

    await skills_handler.cb_decompose(decomposed)

    assert _datas(decomposed.message.edits[-1][1]) == ["skills:cat:equipment"]


@pytest.mark.asyncio
async def test_skills_装备与卸下结果均返回法宝列表(temp_db):
    uid = 9307
    await character.create(uid, f"换装道友{uid}")
    inst_id = await _造法宝(uid, "玄铁剑")
    equip_data = await action_callback_data(uid, f"equip:{inst_id}")
    equipped = _Callback(uid, equip_data)

    await skills_handler.cb_equip(equipped)

    assert _datas(equipped.message.edits[-1][1]) == ["skills:cat:equipment"]

    unequip_data = await action_callback_data(uid, f"eq:unequip:{inst_id}")
    unequipped = _Callback(uid, unequip_data)

    await skills_handler.cb_unequip(unequipped)

    assert _datas(unequipped.message.edits[-1][1]) == ["skills:cat:equipment"]


@pytest.mark.asyncio
async def test_skills_本命法宝认主喂养斩缚走一次性令牌(temp_db):
    uid = 9301
    await _备好元婴道友(uid)
    inst_id = await _造法宝(uid, "天魔刃")
    await _给材料(uid, NATAL.bind_cost("宝"))

    text, markup = await skills_handler.render_equipment_item(uid, inst_id)
    buttons = _buttons(markup)
    bind_data = next(data for data in _datas(markup)
                     if data.startswith(f"natal:bind:{inst_id}:"))
    token_row = await _取令牌(bind_data)

    assert "法宝" in text
    assert "天魔刃" in text
    assert any("认主" in button.text and button.callback_data == bind_data
               for button in buttons)
    assert token_row["user_id"] == uid
    assert token_row["action"] == f"natal:bind:{inst_id}"
    assert token_row["consumed_at"] is None

    bound = _Callback(uid, bind_data)
    await skills_handler.cb_natal_action(bound)
    char = await character.get(uid)
    inst = await db.fetchone(
        "SELECT bound, natal_level FROM item_instances WHERE id=?",
        (inst_id,))

    assert char.natal_instance_id == inst_id
    assert dict(inst) == {"bound": 1, "natal_level": 1}
    assert "本命" in bound.message.edits[-1][0]
    assert "Lv.1" in bound.message.edits[-1][0]
    assert _datas(bound.message.edits[-1][1]) == [
        f"skills:item:{inst_id}", "skills:cat:equipment"]

    again = _Callback(uid, bind_data)
    await skills_handler.cb_natal_action(again)

    assert again.answers and again.answers[0][1] is True
    assert not again.message.edits

    text, markup = await skills_handler.render_equipment_item(uid, inst_id)
    datas = _datas(markup)
    feed_data = next(data for data in datas if data.startswith(f"natal:feed:{inst_id}:"))
    unbind_data = next(data for data in datas if data.startswith(f"natal:unbind:{inst_id}:"))

    assert "本命Lv.1" in text
    assert any("喂养" in button.text and button.callback_data == feed_data
               for button in _buttons(markup))
    assert any("斩" in button.text and button.callback_data == unbind_data
               for button in _buttons(markup))
    assert (await _取令牌(feed_data))["action"] == f"natal:feed:{inst_id}"
    assert (await _取令牌(unbind_data))["action"] == f"natal:unbind:{inst_id}"

    other_inst_id = await _造法宝(uid, "古战佩")
    wrong_feed_data = await action_callback_data(uid, f"natal:feed:{other_inst_id}")
    wrong_feed = _Callback(uid, wrong_feed_data)
    await skills_handler.cb_natal_action(wrong_feed)

    assert "当前本命" in wrong_feed.message.edits[-1][0]
    assert "刷新" in wrong_feed.message.edits[-1][0]

    await _给材料(uid, NATAL.feed_cost(2))
    fed = _Callback(uid, feed_data)
    await skills_handler.cb_natal_action(fed)
    fed_inst = await db.fetchone(
        "SELECT natal_level FROM item_instances WHERE id=?",
        (inst_id,))

    assert fed_inst["natal_level"] == 2
    assert "喂养" in fed.message.edits[-1][0]
    assert "Lv.2" in fed.message.edits[-1][0]

    _text, markup = await skills_handler.render_equipment_item(uid, inst_id)
    unbind_data = next(data for data in _datas(markup)
                       if data.startswith(f"natal:unbind:{inst_id}:"))
    await character.add_stone(uid, NATAL.unbind_cost(2))
    unbound = _Callback(uid, unbind_data)
    await skills_handler.cb_natal_action(unbound)
    char = await character.get(uid)
    inst = await db.fetchone(
        "SELECT bound, natal_level FROM item_instances WHERE id=?",
        (inst_id,))

    assert char.natal_instance_id is None
    assert dict(inst) == {"bound": 1, "natal_level": 0}
    assert "斩" in unbound.message.edits[-1][0]
    assert "本命" in unbound.message.edits[-1][0]

    text, markup = await skills_handler.render_equipment_item(uid, inst_id)
    datas = _datas(markup)

    assert "已斩缚绑定" in text
    assert not any(data.startswith(f"natal:bind:{inst_id}:") for data in datas)
    _text, other_markup = await skills_handler.render_equipment_item(uid, other_inst_id)
    assert any(data.startswith(f"natal:bind:{other_inst_id}:")
               for data in _datas(other_markup))
