from __future__ import annotations

import inspect
import time

import pytest
import pytest_asyncio

from config import realms as R
from handlers import bonds as bonds_handler
from models import db
from services import bonds, character


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "bonds-handlers.db"))
    yield
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
    def __init__(self, user_id: int, text: str = "/master", chat_type: str = "private"):
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


def _datas(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


async def _备好师徒资质(mentor_id: int, disciple_id: int):
    await character.create(mentor_id, f"师尊{mentor_id}")
    await character.set_progress(mentor_id, 3, 0, 0)
    await character.create(disciple_id, f"弟子{disciple_id}")
    await character.set_progress(disciple_id, 1, R.num_stages(1) - 1, 0)


async def _记住群(user_id: int, chat_id: int, now: int):
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=?, last_seen_at=?",
        (chat_id, "问道群", now, "问道群", now))
    await db.execute(
        "INSERT INTO bot_chat_members(chat_id, user_id, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen_at=?",
        (chat_id, user_id, now, now))


async def _激活师徒(mentor_id: int, disciple_id: int, now: int) -> int:
    await _备好师徒资质(mentor_id, disciple_id)
    pending = await bonds.create_pending_mentor_request(
        mentor_id, disciple_id, initiator_id=mentor_id, now=now)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_mentor_request(
        pending["bond_id"], confirmer_id=disciple_id, now=now + 1)
    assert confirmed["status"] == "ok"
    return pending["bond_id"]


@pytest.mark.asyncio
async def test_master_群内入口被私聊护法拦下(temp_db):
    msg = _Message(7001, "/master", chat_type="group")

    await bonds_handler.cmd_master(msg)

    assert msg.answers
    assert "养成诸事请移步私聊" in msg.answers[0][0]


@pytest.mark.asyncio
async def test_master_收徒确认页公示重拜代价(temp_db):
    mentor_id, disciple_id = 7011, 7012
    await _备好师徒资质(mentor_id, disciple_id)

    text, markup = await bonds_handler.render_request_confirm(mentor_id, "收徒", disciple_id)
    datas = _datas(markup)

    assert "解除后重拜，出师累计活跃天数从 0 重计" in text
    assert any(data.startswith("bond:create:") for data in datas)


@pytest.mark.asyncio
async def test_master_收徒确认与拜师成立播报走一次性令牌(temp_db):
    mentor_id, disciple_id = 7021, 7022
    now = 200_000
    await _备好师徒资质(mentor_id, disciple_id)
    await _记住群(mentor_id, -70021, now)

    _text, markup = await bonds_handler.render_request_confirm(mentor_id, "收徒", disciple_id)
    create_data = next(data for data in _datas(markup) if data.startswith("bond:create:"))
    created = _Callback(mentor_id, create_data)
    await bonds_handler.cb_bond_action(created)
    pending = await db.fetchone("SELECT * FROM social_bonds WHERE a_id=? AND b_id=?",
                                (mentor_id, disciple_id))
    assert pending["status"] == "pending"
    assert "拜师帖已递出" in created.message.edits[-1][0]

    # 同一 token 再用会被 consume_action_callback 拦截。
    again = _Callback(mentor_id, create_data)
    await bonds_handler.cb_bond_action(again)
    assert again.answers and again.answers[0][1] is True

    text, markup = await bonds_handler.render_master(disciple_id)
    confirm_data = next(data for data in _datas(markup) if data.startswith("bond:confirm:"))
    confirmed = _Callback(disciple_id, confirm_data)
    await bonds_handler.cb_bond_action(confirmed)
    active = await db.fetchone("SELECT status FROM social_bonds WHERE id=?", (pending["id"],))
    broadcasts = await db.fetchall(
        "SELECT event_type, text FROM social_broadcasts WHERE user_id=?",
        (mentor_id,))

    assert "待你确认" in text
    assert active["status"] == "active"
    assert "师徒名分已定" in confirmed.message.edits[-1][0]
    assert any(row["event_type"] == "mentor.active" and "入室弟子" in row["text"]
               for row in broadcasts)


@pytest.mark.asyncio
async def test_master_首页展示传功出师解除并可传功(temp_db):
    mentor_id, disciple_id = 7031, 7032
    now = int(time.time())
    await _激活师徒(mentor_id, disciple_id, now)
    async with db.transaction() as conn:
        recorded = await bonds.record_disciple_activity(conn, disciple_id, now=now + 10)
    before = await character.get(disciple_id)

    text, markup = await bonds_handler.render_master(mentor_id)
    datas = _datas(markup)
    transfer_data = next(data for data in datas if data.startswith("bond:transfer:"))
    callback = _Callback(mentor_id, transfer_data)
    await bonds_handler.cb_bond_action(callback)
    after = await character.get(disciple_id)

    assert recorded["recorded"] is True
    assert "门下弟子" in text
    assert any(data.startswith("bond:graduate:") for data in datas)
    assert any(data.startswith("bond:dissolve:") for data in datas)
    assert "传功已成" in callback.message.edits[-1][0]
    assert after.cultivation > before.cultivation


def test_master_已注册到命令与路由():
    from bot import app as bot_app

    source = inspect.getsource(bot_app.main)
    commands = [command.command for command in bot_app._COMMANDS]

    assert "master" in commands
    assert "bonds" in source
