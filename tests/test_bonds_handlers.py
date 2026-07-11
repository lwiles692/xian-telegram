from __future__ import annotations

import inspect
import time

import pytest
import pytest_asyncio

from config import realms as R
from handlers import bonds as bonds_handler, me as me_handler
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
    def __init__(self):
        self.sent = []

    async def get_me(self):
        return type("Me", (), {"username": "xian_test_bot"})()

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


class _FailingBot(_Bot):
    async def send_message(self, chat_id, text, reply_markup=None):
        raise RuntimeError("private chat unavailable")


class _RepliedMessage:
    def __init__(self, user_id: int):
        self.from_user = _User(user_id)


class _Message:
    def __init__(self, user_id: int, text: str = "/master", chat_type: str = "private",
                 reply_to_user_id: int | None = None):
        self.from_user = _User(user_id)
        self.text = text
        self.chat = _Chat(chat_type)
        self.reply_to_message = (_RepliedMessage(reply_to_user_id)
                                 if reply_to_user_id is not None else None)
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


async def _备好道侣资质(a_id: int, b_id: int):
    from config import bonds as BONDS

    await character.create(a_id, f"道侣{a_id}")
    await character.set_progress(a_id, 2, 0, 0)
    await character.create(b_id, f"道侣{b_id}")
    await character.set_progress(b_id, 2, 0, 0)
    await character.add_item(a_id, BONDS.PARTNER_TOKEN_ITEM, 1, bound=1)


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


async def _激活道侣(a_id: int, b_id: int, now: int) -> dict:
    await _备好道侣资质(a_id, b_id)
    pending = await bonds.create_pending_partner_request(
        a_id, b_id, initiator_id=a_id, now=now)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_partner_request(
        pending["bond_id"], confirmer_id=b_id, now=now + 1)
    assert confirmed["status"] == "ok"
    return confirmed


@pytest.mark.asyncio
async def test_master_群内入口可展示师徒页面(temp_db):
    await character.create(7001, "群内道友")
    msg = _Message(7001, "/master", chat_type="group")

    await bonds_handler.cmd_master(msg)

    assert msg.answers and msg.answers[0][1] is not None


@pytest.mark.asyncio
async def test_master_回复消息可省略对方ID(temp_db):
    mentor_id, disciple_id = 7002, 7003
    await _备好师徒资质(mentor_id, disciple_id)
    msg = _Message(mentor_id, "/master 收徒", chat_type="group",
                   reply_to_user_id=disciple_id)

    await bonds_handler.cmd_master(msg)

    assert msg.answers and msg.answers[0][1] is None
    assert len(msg.bot.sent) == 1
    sent_chat, _text, markup = msg.bot.sent[0]
    assert sent_chat == mentor_id
    assert any(data.startswith(f"bond:create:{mentor_id}:{disciple_id}:")
               for data in _datas(markup))


@pytest.mark.asyncio
async def test_master_私聊未开启时群内提示私聊入口(temp_db):
    mentor_id, disciple_id = 7004, 7005
    await _备好师徒资质(mentor_id, disciple_id)
    msg = _Message(mentor_id, "/master 收徒", chat_type="group",
                   reply_to_user_id=disciple_id)
    msg.bot = _FailingBot()

    await bonds_handler.cmd_master(msg)

    assert msg.answers and msg.answers[0][1] is None
    assert "私聊入口" in msg.answers[0][0]


@pytest.mark.asyncio
async def test_partner_群内入口被私聊护法拦下(temp_db):
    msg = _Message(7101, "/partner", chat_type="group")

    await bonds_handler.cmd_partner(msg)

    assert msg.answers
    assert "养成诸事请移步私聊" in msg.answers[0][0]


@pytest.mark.asyncio
async def test_partner_群内回复将结契确认发入私聊(temp_db):
    a_id, b_id = 7102, 7103
    await _备好道侣资质(a_id, b_id)
    msg = _Message(a_id, "/partner 结契", chat_type="group",
                   reply_to_user_id=b_id)

    await bonds_handler.cmd_partner(msg)

    assert msg.answers and msg.answers[0][1] is None
    assert len(msg.bot.sent) == 1
    sent_chat, _text, markup = msg.bot.sent[0]
    assert sent_chat == a_id
    assert any(data.startswith(f"bond:pcreate:{a_id}:{b_id}:")
               for data in _datas(markup))


@pytest.mark.asyncio
async def test_master_收徒确认页公示重拜代价(temp_db):
    mentor_id, disciple_id = 7011, 7012
    await _备好师徒资质(mentor_id, disciple_id)

    text, markup = await bonds_handler.render_request_confirm(mentor_id, "收徒", disciple_id)
    datas = _datas(markup)

    assert "解除后重拜，出师累计活跃天数从 0 重计" in text
    assert any(data.startswith("bond:create:") for data in datas)


@pytest.mark.asyncio
async def test_partner_结契确认与道侣首页走一次性令牌(temp_db):
    a_id, b_id = 7111, 7112
    now = 210_000
    await _备好道侣资质(a_id, b_id)

    text, markup = await bonds_handler.render_partner_request_confirm(a_id, b_id)
    create_data = next(data for data in _datas(markup) if data.startswith("bond:pcreate:"))
    created = _Callback(a_id, create_data)
    await bonds_handler.cb_bond_action(created)
    pending = await db.fetchone(
        "SELECT * FROM social_bonds WHERE kind='partner' AND a_id=? AND b_id=?",
        (a_id, b_id))

    assert "递出结契帖确认" in text
    assert "同心结" in text
    assert pending["status"] == "pending"
    assert "结契帖已递出" in created.message.edits[-1][0]

    again = _Callback(a_id, create_data)
    await bonds_handler.cb_bond_action(again)
    assert again.answers and again.answers[0][1] is True

    incoming_text, incoming_markup = await bonds_handler.render_partner(b_id)
    confirm_data = next(data for data in _datas(incoming_markup) if data.startswith("bond:pconfirm:"))
    confirmed = _Callback(b_id, confirm_data)
    await bonds_handler.cb_bond_action(confirmed)
    rows = await db.fetchall(
        "SELECT status FROM social_bonds WHERE kind='partner' "
        "AND ((a_id=? AND b_id=?) OR (a_id=? AND b_id=?))",
        (a_id, b_id, b_id, a_id))

    assert "待你确认的结契帖" in incoming_text
    assert {row["status"] for row in rows} == {"active"}
    assert "道侣名分" in confirmed.message.edits[-1][0]


@pytest.mark.asyncio
async def test_partner_首页展示互赠共修与_me_称号(temp_db):
    a_id, b_id = 7121, 7122
    now = int(time.time())
    await _激活道侣(a_id, b_id, now)
    await character.add_item(a_id, "疗伤丹", 1, bound=1)

    text, markup = await bonds_handler.render_partner(a_id)
    datas = _datas(markup)
    gift_data = next(data for data in datas if data.startswith("bond:pgift:"))
    gift_cb = _Callback(a_id, gift_data)
    await bonds_handler.cb_bond_action(gift_cb)
    invited_text, invited_markup = await bonds_handler.render_partner(a_id)
    invite_data = next(data for data in _datas(invited_markup)
                       if data.startswith("bond:cminvite:"))
    invite_cb = _Callback(a_id, invite_data)
    await bonds_handler.cb_bond_action(invite_cb)
    me_text, _me_markup = await me_handler.render_me(a_id)

    assert "道侣：" in text
    assert "今日可赠：疗伤丹×1" in text
    assert any(data.startswith("bond:cminvite:") for data in datas)
    assert "已赠出 疗伤丹×1" in gift_cb.message.edits[-1][0]
    assert await character.item_qty(b_id, "疗伤丹", bound=1) == 1
    assert "共修：本周可邀道侣" in invited_text
    assert "共修帖已递出" in invite_cb.message.edits[-1][0]
    assert "💞 道侣：" in me_text
    assert "比翼同修" in me_text


@pytest.mark.asyncio
async def test_master_收徒确认与拜师成立播报走一次性令牌(temp_db):
    mentor_id, disciple_id = 7021, 7022
    now = 200_000
    await _备好师徒资质(mentor_id, disciple_id)
    await _记住群(mentor_id, -70021, now)

    _text, markup = await bonds_handler.render_request_confirm(mentor_id, "收徒", disciple_id)
    create_data = next(data for data in _datas(markup) if data.startswith("bond:create:"))
    created = _Callback(mentor_id, create_data, chat_type="group")
    await bonds_handler.cb_bond_action(created)
    pending = await db.fetchone("SELECT * FROM social_bonds WHERE a_id=? AND b_id=?",
                                (mentor_id, disciple_id))
    assert pending["status"] == "pending"
    assert "拜师帖已递出" in created.message.edits[-1][0]

    # 同一 token 再用会被 consume_action_callback 拦截。
    again = _Callback(mentor_id, create_data, chat_type="group")
    await bonds_handler.cb_bond_action(again)
    assert again.answers and again.answers[0][1] is True

    text, markup = await bonds_handler.render_master(disciple_id)
    confirm_data = next(data for data in _datas(markup) if data.startswith("bond:confirm:"))
    confirmed = _Callback(disciple_id, confirm_data, chat_type="group")
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
    assert "partner" in commands
    assert "bonds" in source
