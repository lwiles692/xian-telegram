from __future__ import annotations

import pytest
import pytest_asyncio

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
async def test_skills_本命法宝认主喂养斩缚走一次性令牌(temp_db):
    uid = 9301
    await _备好元婴道友(uid)
    inst_id = await _造法宝(uid, "天魔刃")
    await _给材料(uid, NATAL.bind_cost("宝"))

    text, markup = await skills_handler.render_skills_category(uid, "equipment")
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

    again = _Callback(uid, bind_data)
    await skills_handler.cb_natal_action(again)

    assert again.answers and again.answers[0][1] is True
    assert not again.message.edits

    text, markup = await skills_handler.render_skills_category(uid, "equipment")
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

    _text, markup = await skills_handler.render_skills_category(uid, "equipment")
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

    text, markup = await skills_handler.render_skills_category(uid, "equipment")
    datas = _datas(markup)

    assert "已斩缚绑定" in text
    assert not any(data.startswith(f"natal:bind:{inst_id}:") for data in datas)
    assert any(data.startswith(f"natal:bind:{other_inst_id}:") for data in datas)
