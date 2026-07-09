from __future__ import annotations

from datetime import datetime, timezone
import inspect
import sqlite3
import time

import pytest
import pytest_asyncio

from config import realms as R
from models import db
from services import character, settle


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "bonds.db"))
    yield
    await db.close_db()


async def _列字典(table: str) -> dict[str, object]:
    rows = await db.fetchall(f"PRAGMA table_info({table})")
    return {row["name"]: row for row in rows}


async def _索引字典(table: str) -> dict[str, object]:
    rows = await db.fetchall(f"PRAGMA index_list({table})")
    return {row["name"]: row for row in rows}


async def _索引列(index_name: str) -> list[str]:
    rows = await db.fetchall(f"PRAGMA index_info({index_name})")
    return [row["name"] for row in rows]


async def _备好师徒资质(mentor_id: int, disciple_id: int):
    await character.create(mentor_id, f"云台师尊{mentor_id}")
    await character.set_progress(mentor_id, 3, 0, 0)
    await character.create(disciple_id, f"入门弟子{disciple_id}")
    await character.set_progress(disciple_id, 1, R.num_stages(1) - 1, 0)


async def _备好境界(user_id: int, name: str, realm: int, stage: int | None = None):
    await character.create(user_id, name)
    await character.set_progress(user_id, realm, R.num_stages(realm) - 1 if stage is None else stage, 0)


async def _激活师徒(mentor_id: int, disciple_id: int, now: int) -> int:
    from services import bonds

    await _备好师徒资质(mentor_id, disciple_id)
    pending = await bonds.create_pending_mentor_request(
        mentor_id, disciple_id, initiator_id=mentor_id, now=now)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_mentor_request(
        pending["bond_id"], confirmer_id=disciple_id, now=now + 1)
    assert confirmed["status"] == "ok"
    return pending["bond_id"]


class _StableRng:
    def random(self):
        return 1.0

    def randint(self, low, high):
        return low

    def choice(self, values):
        return values[0]


async def _插入羁绊(
    *,
    kind: str,
    a_id: int,
    b_id: int,
    status: str,
    created_at: int,
    initiator_id: int | None = None,
    expires_at: int | None = None,
    activated_at: int | None = None,
    dissolved_at: int | None = None,
):
    cols = await _列字典("social_bonds")
    values = {
        "kind": kind,
        "a_id": a_id,
        "b_id": b_id,
        "status": status,
        "created_at": created_at,
    }
    if "initiator_id" in cols:
        values["initiator_id"] = initiator_id
    if "expires_at" in cols:
        values["expires_at"] = expires_at
    if "activated_at" in cols:
        values["activated_at"] = activated_at
    if "confirmed_at" in cols:
        values["confirmed_at"] = activated_at
    if "dissolved_at" in cols:
        values["dissolved_at"] = dissolved_at
    if "updated_at" in cols:
        values["updated_at"] = created_at

    names = list(values)
    placeholders = ", ".join("?" for _ in names)
    await db.execute(
        f"INSERT INTO social_bonds({', '.join(names)}) VALUES({placeholders})",
        tuple(values[name] for name in names),
    )


async def _羁绊行(bond_id: int):
    return await db.fetchone("SELECT * FROM social_bonds WHERE id=?", (bond_id,))


async def _师徒行(disciple_id: int):
    return await db.fetchone(
        "SELECT * FROM social_bonds WHERE kind='mentor' AND b_id=? ORDER BY id DESC LIMIT 1",
        (disciple_id,))


async def _记住群(user_id: int, chat_id: int, now: int):
    await db.execute(
        "INSERT INTO bot_chats(chat_id, title, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=?, last_seen_at=?",
        (chat_id, "问道群", now, "问道群", now))
    await db.execute(
        "INSERT INTO bot_chat_members(chat_id, user_id, last_seen_at) VALUES(?,?,?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET last_seen_at=?",
        (chat_id, user_id, now, now))


def _时刻(year: int, month: int, day: int, hour: int = 4) -> int:
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp())


async def _记活跃若干日(user_id: int, start_at: int, days: int):
    from services import bonds

    for offset in range(days):
        async with db.transaction() as conn:
            recorded = await bonds.record_disciple_activity(
                conn, user_id, now=start_at + offset * 24 * 3600)
        assert recorded["recorded"] is True


@pytest.mark.asyncio
async def test_羁绊_schema_重复开库仍成阵(tmp_path):
    path = str(tmp_path / "bonds-schema.db")
    await db.init_db(path)
    await db.init_db(path)
    try:
        bond_cols = await _列字典("social_bonds")
        milestone_cols = await _列字典("bond_milestones")
        transfer_cols = await _列字典("bond_daily_transfers")
        activity_cols = await _列字典("bond_activity_days")
        reward_cols = await _列字典("bond_weekly_rewards")
        title_cols = await _列字典("bond_titles")
        indexes = await _索引字典("social_bonds")
        activity_indexes = await _索引字典("bond_activity_days")
        pending_cols = await _索引列("idx_bonds_pending_expire")
        mentor_cols = await _索引列("idx_bonds_mentor_b")
        partner_cols = await _索引列("idx_bonds_partner_a")
    finally:
        await db.close_db()

    assert set(bond_cols) >= {
        "id", "kind", "a_id", "b_id", "initiator_id", "status", "created_at",
        "expires_at", "activated_at", "confirmed_at", "dissolved_at",
        "active_days", "last_active_day", "updated_at",
    }
    assert set(milestone_cols) >= {"bond_kind", "a_id", "b_id", "milestone"}
    assert set(transfer_cols) >= {
        "bond_kind", "a_id", "b_id", "active_day", "cultivation", "granted_at",
    }
    assert set(activity_cols) >= {
        "bond_kind", "a_id", "b_id", "active_day", "week", "recorded_at",
    }
    assert set(reward_cols) >= {
        "bond_kind", "a_id", "b_id", "week", "active_days", "raw_daohang",
        "daohang", "settled_at",
    }
    assert set(title_cols) >= {"user_id", "title_key", "title", "threshold", "unlocked_at"}

    assert {"idx_bonds_mentor_b", "idx_bonds_partner_a", "idx_bonds_pending_expire",
            "idx_bonds_a", "idx_bonds_b"} <= set(indexes)
    assert "idx_bond_activity_week" in activity_indexes
    assert indexes["idx_bonds_mentor_b"]["unique"] == 1
    assert indexes["idx_bonds_partner_a"]["unique"] == 1
    assert mentor_cols == ["b_id"]
    assert partner_cols == ["a_id"]
    assert "expires_at" in pending_cols

    pk_cols = [
        row["name"]
        for row in sorted(milestone_cols.values(), key=lambda item: item["pk"])
        if row["pk"]
    ]
    assert pk_cols == ["bond_kind", "a_id", "b_id", "milestone"]

    activity_pk = [
        row["name"]
        for row in sorted(activity_cols.values(), key=lambda item: item["pk"])
        if row["pk"]
    ]
    reward_pk = [
        row["name"]
        for row in sorted(reward_cols.values(), key=lambda item: item["pk"])
        if row["pk"]
    ]
    assert activity_pk == ["bond_kind", "a_id", "b_id", "active_day"]
    assert reward_pk == ["bond_kind", "a_id", "b_id", "week"]


def test_羁绊常量_四十八时辰与七日法度():
    from config import bonds as BONDS

    assert BONDS.PENDING_EXPIRE_SECONDS == 48 * 3600
    assert BONDS.DISSOLVE_COOLDOWN_SECONDS == 7 * 24 * 3600
    assert BONDS.MAX_ACTIVE_DISCIPLES == 3
    assert BONDS.KIND_MENTOR == "mentor"
    assert BONDS.KIND_PARTNER == "partner"
    assert BONDS.STATUS_GRADUATED == "graduated"
    assert BONDS.DISCIPLE_SECLUSION_PCT == 0.05
    assert BONDS.GRADUATION_ACTIVE_DAYS_REQUIRED == 8
    assert BONDS.GRADUATION_MIN_REALM == 3
    assert BONDS.GRADUATION_BOUND_ITEMS
    assert BONDS.GRADUATION_MENTOR_DAOHANG > 0
    assert BONDS.GRADUATION_DISCIPLE_DAOHANG > 0
    assert [item[0] for item in BONDS.MENTOR_TITLE_THRESHOLDS] == [1, 3, 5]
    assert BONDS.MENTOR_WEEKLY_DAOHANG_PER_ACTIVE_DAY == 5
    assert BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE == 30
    assert BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE < settle.OVERFLOW_DAOHANG_WEEKLY_CAP
    for realm, amount in BONDS.MENTOR_TRANSFER_CULTIVATION_BY_REALM.items():
        one_hour = settle.seclusion_gain(realm, 0, 0, 3600, root_bone=0)
        assert amount < one_hour * 0.5


@pytest.mark.asyncio
async def test_pending_四十八时辰后_旧帖过期新帖仍候命(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 200_000
    await _插入羁绊(
        kind=BONDS.KIND_MENTOR,
        a_id=101,
        b_id=201,
        status=BONDS.STATUS_PENDING,
        created_at=now - BONDS.PENDING_EXPIRE_SECONDS - 10,
        expires_at=now - 10,
    )
    await _插入羁绊(
        kind=BONDS.KIND_MENTOR,
        a_id=102,
        b_id=202,
        status=BONDS.STATUS_PENDING,
        created_at=now - BONDS.PENDING_EXPIRE_SECONDS + 10,
        expires_at=now + 10,
    )

    await bonds.expire_pending(now=now)

    rows = await db.fetchall(
        "SELECT b_id, status FROM social_bonds WHERE b_id IN (201, 202) ORDER BY b_id")
    assert {row["b_id"]: row["status"] for row in rows} == {
        201: BONDS.STATUS_EXPIRED,
        202: BONDS.STATUS_PENDING,
    }


@pytest.mark.asyncio
async def test_拒绝与过期不结冷却_解除七日后山门再开(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 500_000
    await _备好师徒资质(301, 401)
    await _插入羁绊(
        kind=BONDS.KIND_MENTOR,
        a_id=301,
        b_id=401,
        status=BONDS.STATUS_DECLINED,
        created_at=now - 100,
    )
    declined = await bonds.can_start_mentor_request(301, 401, now=now)
    assert declined["status"] == "ok"

    await _备好师徒资质(302, 402)
    await _插入羁绊(
        kind=BONDS.KIND_MENTOR,
        a_id=302,
        b_id=402,
        status=BONDS.STATUS_EXPIRED,
        created_at=now - BONDS.PENDING_EXPIRE_SECONDS - 10,
        expires_at=now - 10,
    )
    expired = await bonds.can_start_mentor_request(302, 402, now=now)
    assert expired["status"] == "ok"

    await _备好师徒资质(303, 403)
    dissolved_at = now - 3600
    await _插入羁绊(
        kind=BONDS.KIND_MENTOR,
        a_id=303,
        b_id=403,
        status=BONDS.STATUS_DISSOLVED,
        created_at=now - 7200,
        dissolved_at=dissolved_at,
    )
    expected_until = dissolved_at + BONDS.DISSOLVE_COOLDOWN_SECONDS

    cooling = await bonds.can_start_mentor_request(303, 403, now=now)
    assert cooling["status"] == "cooldown"
    assert cooling["cooldown_until"] == expected_until
    assert await bonds.cooldown_until(303, now=now) == expected_until
    assert await bonds.cooldown_until(403, now=now) == expected_until

    reopened = await bonds.can_start_mentor_request(303, 403, now=expected_until)
    assert reopened["status"] == "ok"


@pytest.mark.asyncio
async def test_徒弟同一时刻只能拜一位师父_数据库护法拦双拜(temp_db):
    from config import bonds as BONDS

    await _插入羁绊(
        kind=BONDS.KIND_MENTOR,
        a_id=501,
        b_id=601,
        status=BONDS.STATUS_PENDING,
        created_at=1000,
        expires_at=1000 + BONDS.PENDING_EXPIRE_SECONDS,
    )

    with pytest.raises(sqlite3.IntegrityError):
        await _插入羁绊(
            kind=BONDS.KIND_MENTOR,
            a_id=502,
            b_id=601,
            status=BONDS.STATUS_ACTIVE,
            created_at=1001,
            activated_at=1001,
        )


@pytest.mark.asyncio
async def test_同心结镜像行_同一人不可同时结两缘(temp_db):
    from config import bonds as BONDS

    await _插入羁绊(
        kind=BONDS.KIND_PARTNER,
        a_id=701,
        b_id=702,
        status=BONDS.STATUS_PENDING,
        created_at=2000,
        expires_at=2000 + BONDS.PENDING_EXPIRE_SECONDS,
    )

    with pytest.raises(sqlite3.IntegrityError):
        await _插入羁绊(
            kind=BONDS.KIND_PARTNER,
            a_id=701,
            b_id=703,
            status=BONDS.STATUS_ACTIVE,
            created_at=2001,
            activated_at=2001,
        )


@pytest.mark.asyncio
async def test_活跃日计数_新羁绊默认尚未启卷(temp_db):
    from config import bonds as BONDS

    await _插入羁绊(
        kind=BONDS.KIND_MENTOR,
        a_id=801,
        b_id=901,
        status=BONDS.STATUS_PENDING,
        created_at=3000,
        expires_at=3000 + BONDS.PENDING_EXPIRE_SECONDS,
    )

    row = await db.fetchone(
        "SELECT active_days, last_active_day FROM social_bonds WHERE a_id=? AND b_id=?",
        (801, 901),
    )
    assert row["active_days"] == 0
    assert row["last_active_day"] is None


@pytest.mark.asyncio
async def test_拜师境界门槛_元婴师父收筑基徒弟方可候命(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 610_000
    await _备好境界(1001, "金丹师兄1001", 2, 0)
    await _备好境界(1002, "筑基弟子1002", 1)
    low_mentor = await bonds.create_pending_mentor_request(
        1001, 1002, initiator_id=1001, now=now)
    assert low_mentor["status"] == "mentor_realm_low"

    await _备好境界(1003, "元婴师尊1003", 3, 0)
    await _备好境界(1004, "金丹道友1004", 2, 0)
    high_disciple = await bonds.create_pending_mentor_request(
        1003, 1004, initiator_id=1003, now=now + 1)
    assert high_disciple["status"] == "disciple_realm_high"

    await _备好境界(1005, "元婴师尊1005", 3, 0)
    await _备好境界(1006, "筑基圆满1006", 1)
    ok = await bonds.create_pending_mentor_request(
        1005, 1006, initiator_id=1005, now=now + 2)
    assert ok["status"] == "ok"

    row = await _羁绊行(ok["bond_id"])
    assert row["kind"] == BONDS.KIND_MENTOR
    assert row["a_id"] == 1005
    assert row["b_id"] == 1006
    assert row["initiator_id"] == 1005
    assert row["status"] == BONDS.STATUS_PENDING
    assert row["created_at"] == now + 2
    assert row["expires_at"] == now + 2 + BONDS.PENDING_EXPIRE_SECONDS
    assert row["active_days"] == 0


@pytest.mark.asyncio
async def test_拜师确认_只有另一方可确认并归入活跃(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 620_000
    await _备好师徒资质(1101, 1201)
    pending = await bonds.create_pending_mentor_request(
        1101, 1201, initiator_id=1101, now=now)
    assert pending["status"] == "ok"
    bond_id = pending["bond_id"]

    self_confirm = await bonds.confirm_pending_mentor_request(
        bond_id, confirmer_id=1101, now=now + 10)
    assert self_confirm["status"] == "need_counterparty"

    stranger_confirm = await bonds.confirm_pending_mentor_request(
        bond_id, confirmer_id=9999, now=now + 20)
    assert stranger_confirm["status"] == "forbidden"

    confirmed_at = now + 30
    confirmed = await bonds.confirm_pending_mentor_request(
        bond_id, confirmer_id=1201, now=confirmed_at)
    assert confirmed["status"] == "ok"

    row = await _羁绊行(bond_id)
    assert row["status"] == BONDS.STATUS_ACTIVE
    assert row["activated_at"] == confirmed_at
    assert row["confirmed_at"] == confirmed_at
    assert row["updated_at"] == confirmed_at
    assert row["active_days"] == 0


@pytest.mark.asyncio
async def test_拒绝待确认拜师_任一方拒绝不落冷却(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 630_000
    await _备好师徒资质(1301, 1401)
    by_mentor = await bonds.create_pending_mentor_request(
        1301, 1401, initiator_id=1301, now=now)
    assert by_mentor["status"] == "ok"
    declined_by_disciple = await bonds.decline_pending_mentor_request(
        by_mentor["bond_id"], user_id=1401, now=now + 10)
    assert declined_by_disciple["status"] == "ok"

    row = await _羁绊行(by_mentor["bond_id"])
    assert row["status"] == BONDS.STATUS_DECLINED
    assert row["updated_at"] == now + 10
    assert row["dissolved_at"] is None

    retry = await bonds.can_start_mentor_request(1301, 1401, now=now + 10)
    assert retry["status"] == "ok"

    await _备好师徒资质(1302, 1402)
    by_disciple = await bonds.create_pending_mentor_request(
        1302, 1402, initiator_id=1402, now=now + 20)
    assert by_disciple["status"] == "ok"
    declined_by_mentor = await bonds.decline_pending_mentor_request(
        by_disciple["bond_id"], user_id=1302, now=now + 30)
    assert declined_by_mentor["status"] == "ok"

    row = await _羁绊行(by_disciple["bond_id"])
    assert row["status"] == BONDS.STATUS_DECLINED
    assert row["updated_at"] == now + 30
    assert row["dissolved_at"] is None

    retry = await bonds.can_start_mentor_request(1302, 1402, now=now + 30)
    assert retry["status"] == "ok"


@pytest.mark.asyncio
async def test_解除活跃拜师_七日冷却后重拜活跃日归零(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 640_000
    await _备好师徒资质(1501, 1601)
    pending = await bonds.create_pending_mentor_request(
        1501, 1601, initiator_id=1501, now=now)
    assert pending["status"] == "ok"
    confirmed = await bonds.confirm_pending_mentor_request(
        pending["bond_id"], confirmer_id=1601, now=now + 10)
    assert confirmed["status"] == "ok"

    dissolved_at = now + 100
    dissolved = await bonds.dissolve_active_bond(
        pending["bond_id"], user_id=1501, now=dissolved_at)
    assert dissolved["status"] == "ok"

    row = await _羁绊行(pending["bond_id"])
    assert row["status"] == BONDS.STATUS_DISSOLVED
    assert row["dissolved_at"] == dissolved_at
    assert row["updated_at"] == dissolved_at

    expected_until = dissolved_at + BONDS.DISSOLVE_COOLDOWN_SECONDS
    blocked = await bonds.can_start_mentor_request(1501, 1601, now=dissolved_at)
    assert blocked["status"] == "cooldown"
    assert blocked["cooldown_until"] == expected_until
    assert await bonds.cooldown_until(1501, now=dissolved_at) == expected_until
    assert await bonds.cooldown_until(1601, now=dissolved_at) == expected_until

    reopened = await bonds.can_start_mentor_request(1501, 1601, now=expected_until)
    assert reopened["status"] == "ok"

    second_pending = await bonds.create_pending_mentor_request(
        1501, 1601, initiator_id=1601, now=expected_until)
    assert second_pending["status"] == "ok"
    second_confirmed_at = expected_until + 5
    second_confirmed = await bonds.confirm_pending_mentor_request(
        second_pending["bond_id"], confirmer_id=1501, now=second_confirmed_at)
    assert second_confirmed["status"] == "ok"

    row = await _羁绊行(second_pending["bond_id"])
    assert row["status"] == BONDS.STATUS_ACTIVE
    assert row["activated_at"] == second_confirmed_at
    assert row["confirmed_at"] == second_confirmed_at
    assert row["active_days"] == 0

    second_dissolved_at = second_confirmed_at + 20
    second_dissolved = await bonds.dissolve_active_bond(
        second_pending["bond_id"], user_id=1601, now=second_dissolved_at)
    assert second_dissolved["status"] == "ok"

    row = await _羁绊行(second_pending["bond_id"])
    assert row["status"] == BONDS.STATUS_DISSOLVED
    assert row["dissolved_at"] == second_dissolved_at


@pytest.mark.asyncio
async def test_师父已有三名活跃徒弟_第四帖返回过载(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 650_000
    mentor_id = 1701
    await _备好境界(mentor_id, "元婴师尊1701", 3, 0)
    for offset, disciple_id in enumerate((1801, 1802, 1803), start=1):
        await _插入羁绊(
            kind=BONDS.KIND_MENTOR,
            a_id=mentor_id,
            b_id=disciple_id,
            initiator_id=mentor_id,
            status=BONDS.STATUS_ACTIVE,
            created_at=now - offset,
            activated_at=now - offset,
        )

    await _备好境界(1804, "新入山门1804", 1)
    result = await bonds.create_pending_mentor_request(
        mentor_id, 1804, initiator_id=mentor_id, now=now)
    assert result["status"] == "too_many"
    assert result["limit"] == BONDS.MAX_ACTIVE_DISCIPLES


@pytest.mark.asyncio
async def test_重复确认已活跃拜师_返回稳定状态且不改旧时辰(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 660_000
    await _备好师徒资质(1901, 2001)
    pending = await bonds.create_pending_mentor_request(
        1901, 2001, initiator_id=1901, now=now)
    assert pending["status"] == "ok"

    confirmed_at = now + 10
    first = await bonds.confirm_pending_mentor_request(
        pending["bond_id"], confirmer_id=2001, now=confirmed_at)
    assert first["status"] == "ok"

    second = await bonds.confirm_pending_mentor_request(
        pending["bond_id"], confirmer_id=2001, now=now + 20)
    assert second["status"] == "not_pending"
    assert second["bond_status"] == BONDS.STATUS_ACTIVE

    row = await _羁绊行(pending["bond_id"])
    assert row["status"] == BONDS.STATUS_ACTIVE
    assert row["activated_at"] == confirmed_at
    assert row["confirmed_at"] == confirmed_at
    assert row["active_days"] == 0


@pytest.mark.asyncio
async def test_活跃日记录_同日去重跨日递增且解除冻结(temp_db):
    from services import bonds

    now = 670_000
    bond_id = await _激活师徒(2101, 2201, now)

    async with db.transaction() as conn:
        first = await bonds.record_disciple_activity(conn, 2201, now=now + 10)
        same_day = await bonds.record_disciple_activity(conn, 2201, now=now + 20)
        today = await bonds.disciple_activity_today(conn, 2201, now=now + 20)

    row = await _羁绊行(bond_id)
    assert first["recorded"] is True
    assert same_day["recorded"] is False
    assert today["active_today"] is True
    assert row["active_days"] == 1
    assert row["last_active_day"] == time.strftime(
        "%Y-%m-%d", time.gmtime(now + 10 + bonds.ACTIVE_DAY_TZ_OFFSET_SECONDS))

    next_day = now + 24 * 3600
    async with db.transaction() as conn:
        crossed = await bonds.record_disciple_activity(conn, 2201, now=next_day)
    row = await _羁绊行(bond_id)
    assert crossed["recorded"] is True
    assert row["active_days"] == 2

    dissolved = await bonds.dissolve_active_bond(bond_id, user_id=2101, now=next_day + 10)
    assert dissolved["status"] == "ok"
    async with db.transaction() as conn:
        frozen = await bonds.record_disciple_activity(conn, 2201, now=next_day + 24 * 3600)
        today = await bonds.disciple_activity_today(conn, 2201, now=next_day + 24 * 3600)
    row = await _羁绊行(bond_id)
    assert frozen["recorded"] is False
    assert today["status"] == "no_active_bond"
    assert row["active_days"] == 2


@pytest.mark.asyncio
async def test_前台行为挂接_收功历练秘境任务按日入卷(temp_db, monkeypatch):
    from services import dungeon, explore, game_events, quests

    now = 700_000
    disciple_id = 2401
    await _激活师徒(2301, disciple_id, now)

    def fake_simulate(player, mob, **kwargs):
        return {"winner": player, "log": ["道友出手，妖邪退散。"],
                "a_hp": player.hp, "d_hp": 0, "rounds": 1, "reason": "defeat"}

    monkeypatch.setattr(explore, "simulate", fake_simulate)
    monkeypatch.setattr(dungeon, "simulate", fake_simulate)

    await character.start_seclusion(disciple_id, now=now + 60)
    collected = await character.collect_seclusion(disciple_id, now=now + 3660)
    row = await _师徒行(disciple_id)
    assert collected["status"] == "collected"
    assert collected["bond_activity"]["recorded"] is True
    assert row["active_days"] == 1

    started = await explore.start(disciple_id, "后山", now=now + 4000, rng=_StableRng())
    explored = await explore.collect(disciple_id, now=started["finish_at"], rng=_StableRng())
    row = await _师徒行(disciple_id)
    assert explored["status"] == "ok"
    assert explored["win"] is True
    assert row["active_days"] == 1

    day_two = now + 24 * 3600
    async with db.transaction() as conn:
        await game_events.emit_conn(conn, disciple_id, "explore.win", {"amount": 3}, now=day_two)
    claimed = await quests.claim(disciple_id, "daily_explore", now=day_two)
    row = await _师徒行(disciple_id)
    assert claimed["status"] == "ok"
    assert claimed["bond_activity"]["recorded"] is True
    assert row["active_days"] == 2

    day_three = now + 2 * 24 * 3600
    started = await dungeon.start(disciple_id, "lingxi", now=day_three, rng=_StableRng())
    delved = await dungeon.collect(disciple_id, now=started["finish_at"], rng=_StableRng())
    row = await _师徒行(disciple_id)
    assert delved["status"] == "ok"
    assert delved["cleared"] > 0
    assert row["active_days"] == 3


@pytest.mark.asyncio
async def test_前台行为挂接_历练秘境败退仍计当日活跃(temp_db, monkeypatch):
    from services import dungeon, explore

    now = 800_000
    disciple_id = 2601
    await _激活师徒(2501, disciple_id, now)

    def fake_loss(player, mob, **kwargs):
        return {"winner": mob, "log": ["道友一时失手，被迫退回山门。"],
                "a_hp": 0, "d_hp": mob.hp, "rounds": 1, "reason": "defeat"}

    monkeypatch.setattr(explore, "simulate", fake_loss)
    monkeypatch.setattr(dungeon, "simulate", fake_loss)

    started = await explore.start(disciple_id, "后山", now=now + 100, rng=_StableRng())
    explored = await explore.collect(disciple_id, now=started["finish_at"], rng=_StableRng())
    row = await _师徒行(disciple_id)
    assert explored["status"] == "ok"
    assert explored["win"] is False
    assert explored["bond_activity"]["recorded"] is True
    assert row["active_days"] == 1

    next_day = now + 24 * 3600
    started = await dungeon.start(disciple_id, "lingxi", now=next_day, rng=_StableRng())
    delved = await dungeon.collect(disciple_id, now=started["finish_at"], rng=_StableRng())
    row = await _师徒行(disciple_id)
    assert delved["status"] == "ok"
    assert delved["cleared"] == 0
    assert delved["bond_activity"]["recorded"] is True
    assert row["active_days"] == 2


@pytest.mark.asyncio
async def test_每日传功_需徒弟今日活跃且每对每日一次(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 900_000
    mentor_id, disciple_id = 2701, 2801
    await _激活师徒(mentor_id, disciple_id, now)
    before = await character.get(disciple_id)

    inactive = await bonds.grant_daily_mentor_transfer(
        mentor_id, disciple_id, now=now + 10)
    assert inactive["status"] == "inactive_today"

    async with db.transaction() as conn:
        recorded = await bonds.record_disciple_activity(conn, disciple_id, now=now + 20)
    assert recorded["recorded"] is True

    first = await bonds.grant_daily_mentor_transfer(
        mentor_id, disciple_id, now=now + 30)
    after_first = await character.get(disciple_id)
    assert first["status"] == "ok"
    assert first["cultivation"] == BONDS.MENTOR_TRANSFER_CULTIVATION_BY_REALM[before.realm]
    assert after_first.cultivation == before.cultivation + first["cultivation"]

    duplicate = await bonds.grant_daily_mentor_transfer(
        mentor_id, disciple_id, now=now + 40)
    assert duplicate["status"] == "daily_done"
    after_duplicate = await character.get(disciple_id)
    assert after_duplicate.cultivation == after_first.cultivation

    next_day = now + 24 * 3600
    async with db.transaction() as conn:
        recorded = await bonds.record_disciple_activity(conn, disciple_id, now=next_day)
    assert recorded["recorded"] is True

    second = await bonds.grant_daily_mentor_transfer(
        mentor_id, disciple_id, now=next_day + 10)
    after_second = await character.get(disciple_id)
    assert second["status"] == "ok"
    assert after_second.cultivation == after_first.cultivation + second["cultivation"]


@pytest.mark.asyncio
async def test_徒弟突破金丹_师父里程碑道行与播报终身一次(temp_db, monkeypatch):
    from config import bonds as BONDS
    from services import bonds, breakthrough

    now = 1_000_000
    mentor_id, disciple_id = 2901, 3001
    await _激活师徒(mentor_id, disciple_id, now)
    await _记住群(mentor_id, -10001, now)
    last_stage = R.num_stages(1) - 1
    cost = R.advance_cost(1, last_stage)
    await character.set_progress(disciple_id, 1, last_stage, cost)
    await character.add_item(disciple_id, "金丹", 1)
    before = await character.get(mentor_id)
    monkeypatch.setattr(breakthrough.random, "random", lambda: 0.0)
    monkeypatch.setattr(breakthrough.random, "randint", lambda _a, _b: 1)

    start = await breakthrough.try_advance(disciple_id, now=now + 10)
    result = start
    for offset in range(3):
        result = await breakthrough.choose_tribulation_action(
            disciple_id, "artifact", now=now + 11 + offset)

    mentor = await character.get(mentor_id)
    milestone = await db.fetchone(
        "SELECT * FROM bond_milestones WHERE bond_kind=? AND a_id=? AND b_id=? AND milestone=?",
        (BONDS.KIND_MENTOR, mentor_id, disciple_id, "jindan"))
    broadcasts = await db.fetchall(
        "SELECT event_type, text FROM social_broadcasts WHERE user_id=? ORDER BY id",
        (mentor_id,))

    assert start["status"] == "tribulation_choice"
    assert result["status"] == "big_success"
    assert result["mentor_milestone"]["status"] == "ok"
    assert result["mentor_milestone"]["milestone"] == "jindan"
    assert mentor.daohang == before.daohang + BONDS.MENTOR_MILESTONE_REWARDS["jindan"]["daohang"]
    assert milestone["claimed_at"] == now + 13
    assert any(row["event_type"] == "mentor.milestone" and "破入金丹" in row["text"]
               for row in broadcasts)

    async with db.transaction() as conn:
        duplicate = await bonds.handle_disciple_breakthrough_conn(
            conn, disciple_id, 2, 0, now + 20)
    mentor_after = await character.get(mentor_id)
    assert duplicate["status"] == "already_claimed"
    assert mentor_after.daohang == mentor.daohang


@pytest.mark.asyncio
async def test_出师双条件_奖励全绑定且出师后停传承(temp_db):
    from config import bonds as BONDS
    from services import bonds, market

    now = 1_100_000
    mentor_id, disciple_id = 3101, 3201
    bond_id = await _激活师徒(mentor_id, disciple_id, now)
    await _记住群(mentor_id, -10002, now)

    low_realm = await bonds.graduate_mentor_bond(bond_id, user_id=disciple_id, now=now + 10)
    assert low_realm["status"] == "disciple_realm_low"

    await character.set_progress(disciple_id, 3, 0, 0)
    low_days = await bonds.graduate_mentor_bond(bond_id, user_id=mentor_id, now=now + 20)
    assert low_days["status"] == "active_days_low"
    assert low_days["need"] == BONDS.GRADUATION_ACTIVE_DAYS_REQUIRED

    await db.execute(
        "UPDATE social_bonds SET active_days=? WHERE id=?",
        (BONDS.GRADUATION_ACTIVE_DAYS_REQUIRED, bond_id))
    before_mentor = await character.get(mentor_id)
    before_disciple = await character.get(disciple_id)
    graduated = await bonds.graduate_mentor_bond(bond_id, user_id=disciple_id, now=now + 30)
    row = await _羁绊行(bond_id)
    after_mentor = await character.get(mentor_id)
    after_disciple = await character.get(disciple_id)

    assert graduated["status"] == "ok"
    assert row["status"] == BONDS.STATUS_GRADUATED
    assert after_mentor.daohang == before_mentor.daohang + BONDS.GRADUATION_MENTOR_DAOHANG
    assert after_disciple.daohang == before_disciple.daohang + BONDS.GRADUATION_DISCIPLE_DAOHANG
    assert await bonds.cooldown_until(mentor_id, now=now + 30) is None
    assert await bonds.grant_daily_mentor_transfer(mentor_id, disciple_id, now=now + 40) == {
        "status": "not_active"}

    for item_key, qty in BONDS.GRADUATION_BOUND_ITEMS.items():
        assert await character.item_qty(mentor_id, item_key, bound=1) == qty
        assert await character.item_qty(disciple_id, item_key, bound=1) == qty
        assert await character.item_qty(mentor_id, item_key, bound=0) == 0
        assert await character.item_qty(disciple_id, item_key, bound=0) == 0
        listed = await market.create_listing(disciple_id, item_key, 1, 100, now=now + 50)
        assert listed["status"] == "no_item"

    duplicate = await bonds.graduate_mentor_bond(bond_id, user_id=mentor_id, now=now + 60)
    assert duplicate["status"] == "already_graduated"
    broadcasts = await db.fetchall(
        "SELECT event_type, text FROM social_broadcasts WHERE user_id=? ORDER BY id",
        (mentor_id,))
    assert any(row["event_type"] == "mentor.graduate" and "功成出师" in row["text"]
               for row in broadcasts)
    assert any(row["event_type"] == "mentor.title" and "授业真人" in row["text"]
               for row in broadcasts)


@pytest.mark.asyncio
async def test_桃李称号_累计出师一三五名递进解锁(temp_db):
    from config import bonds as BONDS
    from services import bonds

    now = 1_200_000
    mentor_id = 3301
    unlocked = []
    for idx in range(1, 6):
        disciple_id = 3400 + idx
        bond_id = await _激活师徒(mentor_id, disciple_id, now + idx * 100)
        await character.set_progress(disciple_id, 3, 0, 0)
        await db.execute(
            "UPDATE social_bonds SET active_days=? WHERE id=?",
            (BONDS.GRADUATION_ACTIVE_DAYS_REQUIRED, bond_id))
        res = await bonds.graduate_mentor_bond(
            bond_id, user_id=mentor_id, now=now + idx * 100 + 50)
        assert res["status"] == "ok"
        unlocked.extend(title["title"] for title in res["titles"])

    rows = await db.fetchall(
        "SELECT title, threshold FROM bond_titles WHERE user_id=? ORDER BY threshold",
        (mentor_id,))
    graduate_rows = await db.fetchall(
        "SELECT milestone FROM bond_milestones WHERE a_id=? AND milestone=?",
        (mentor_id, BONDS.GRADUATION_MILESTONE))

    assert unlocked == ["授业真人", "桃李盈门", "一代宗师"]
    assert [(row["threshold"], row["title"]) for row in rows] == [
        (1, "授业真人"), (3, "桃李盈门"), (5, "一代宗师")]
    assert len(graduate_rows) == 5


@pytest.mark.asyncio
async def test_周活跃回报_按活跃日计且重复结算幂等(temp_db):
    from config import bonds as BONDS
    from services import bonds

    start = _时刻(2026, 7, 6)
    settle_at = _时刻(2026, 7, 12, hour=15)
    mentor_id, disciple_id = 3501, 3601
    await _激活师徒(mentor_id, disciple_id, start - 100)
    await _记活跃若干日(disciple_id, start, 3)
    before = await character.get(mentor_id)

    first = await bonds.settle_weekly_mentor_activity(now=settle_at)
    after_first = await character.get(mentor_id)
    duplicate = await bonds.settle_weekly_mentor_activity(now=settle_at)
    after_duplicate = await character.get(mentor_id)
    reward = await db.fetchone(
        "SELECT * FROM bond_weekly_rewards WHERE a_id=? AND b_id=?",
        (mentor_id, disciple_id))
    weekly = await db.fetchone(
        "SELECT overflow_daohang FROM weekly_activity WHERE user_id=? AND week=?",
        (mentor_id, first["week"]))
    events = await db.fetchall(
        "SELECT event_type, amount FROM path_events WHERE user_id=?",
        (mentor_id,))

    expected = 3 * BONDS.MENTOR_WEEKLY_DAOHANG_PER_ACTIVE_DAY
    assert first["status"] == "ok"
    assert first["settled"] == 1
    assert first["rewards"][0]["active_days"] == 3
    assert first["rewards"][0]["raw_daohang"] == expected
    assert first["rewards"][0]["daohang"] == expected
    assert after_first.daohang == before.daohang + expected
    assert duplicate["settled"] == 0
    assert after_duplicate.daohang == after_first.daohang
    assert reward["active_days"] == 3
    assert reward["raw_daohang"] == expected
    assert reward["daohang"] == expected
    assert weekly["overflow_daohang"] == expected
    assert [(row["event_type"], row["amount"]) for row in events] == [
        ("mentor_weekly_activity", expected)]


@pytest.mark.asyncio
async def test_周活跃回报_满勤徒弟按单徒上限封顶(temp_db):
    from config import bonds as BONDS
    from services import bonds

    start = _时刻(2026, 7, 6)
    settle_at = _时刻(2026, 7, 12, hour=15)
    mentor_id, disciple_id = 3701, 3801
    await _激活师徒(mentor_id, disciple_id, start - 100)
    await _记活跃若干日(disciple_id, start, 7)
    before = await character.get(mentor_id)

    settled = await bonds.settle_weekly_mentor_activity(now=settle_at)
    after = await character.get(mentor_id)
    reward = await db.fetchone(
        "SELECT active_days, raw_daohang, daohang FROM bond_weekly_rewards "
        "WHERE a_id=? AND b_id=?",
        (mentor_id, disciple_id))

    assert settled["settled"] == 1
    assert settled["rewards"][0]["active_days"] == 7
    assert reward["active_days"] == 7
    assert reward["raw_daohang"] == BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE
    assert reward["daohang"] == BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE
    assert after.daohang == before.daohang + BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE


@pytest.mark.asyncio
async def test_周活跃回报_计入溢出道行周上限(temp_db):
    from config import bonds as BONDS
    from services import bonds

    start = _时刻(2026, 7, 6)
    settle_at = _时刻(2026, 7, 12, hour=15)
    mentor_id, disciple_id = 3901, 4001
    await _激活师徒(mentor_id, disciple_id, start - 100)
    await _记活跃若干日(disciple_id, start, 7)
    week = time.strftime("%Y-%W", time.localtime(settle_at))
    used = settle.OVERFLOW_DAOHANG_WEEKLY_CAP - 10
    await db.execute(
        "INSERT INTO weekly_activity(user_id, week, overflow_daohang) VALUES(?,?,?)",
        (mentor_id, week, used))
    before = await character.get(mentor_id)

    settled = await bonds.settle_weekly_mentor_activity(now=settle_at)
    after = await character.get(mentor_id)
    weekly = await db.fetchone(
        "SELECT overflow_daohang FROM weekly_activity WHERE user_id=? AND week=?",
        (mentor_id, week))
    reward = await db.fetchone(
        "SELECT raw_daohang, daohang FROM bond_weekly_rewards WHERE a_id=? AND b_id=?",
        (mentor_id, disciple_id))

    assert settled["rewards"][0]["raw_daohang"] == BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE
    assert settled["rewards"][0]["daohang"] == 10
    assert after.daohang == before.daohang + 10
    assert weekly["overflow_daohang"] == settle.OVERFLOW_DAOHANG_WEEKLY_CAP
    assert reward["raw_daohang"] == BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE
    assert reward["daohang"] == 10


@pytest.mark.asyncio
async def test_周活跃回报_出师后停发(temp_db):
    from config import bonds as BONDS
    from services import bonds

    start = _时刻(2026, 7, 6)
    settle_at = _时刻(2026, 7, 12, hour=15)
    mentor_id, disciple_id = 4101, 4201
    bond_id = await _激活师徒(mentor_id, disciple_id, start - 100)
    await _记活跃若干日(disciple_id, start, 7)
    await character.set_progress(disciple_id, 3, 0, 0)
    await db.execute(
        "UPDATE social_bonds SET active_days=? WHERE id=?",
        (BONDS.GRADUATION_ACTIVE_DAYS_REQUIRED, bond_id))
    graduated = await bonds.graduate_mentor_bond(
        bond_id, user_id=mentor_id, now=start + 7 * 24 * 3600)
    before = await character.get(mentor_id)

    settled = await bonds.settle_weekly_mentor_activity(now=settle_at)
    after = await character.get(mentor_id)
    rewards = await db.fetchall(
        "SELECT * FROM bond_weekly_rewards WHERE a_id=? AND b_id=?",
        (mentor_id, disciple_id))

    assert graduated["status"] == "ok"
    assert settled["settled"] == 0
    assert after.daohang == before.daohang
    assert rewards == []


@pytest.mark.asyncio
async def test_周活跃回报_三名满勤徒弟仍远低于周上限(temp_db):
    from config import bonds as BONDS
    from services import bonds

    start = _时刻(2026, 7, 6)
    settle_at = _时刻(2026, 7, 12, hour=15)
    mentor_id = 4301
    disciple_ids = [4401, 4402, 4403]
    for disciple_id in disciple_ids:
        await _激活师徒(mentor_id, disciple_id, start - 100 + disciple_id)
        await _记活跃若干日(disciple_id, start, 7)
    before = await character.get(mentor_id)

    settled = await bonds.settle_weekly_mentor_activity(now=settle_at)
    after = await character.get(mentor_id)
    weekly = await db.fetchone(
        "SELECT overflow_daohang FROM weekly_activity WHERE user_id=? AND week=?",
        (mentor_id, settled["week"]))

    expected = len(disciple_ids) * BONDS.MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE
    assert settled["settled"] == len(disciple_ids)
    assert sum(row["daohang"] for row in settled["rewards"]) == expected
    assert after.daohang == before.daohang + expected
    assert weekly["overflow_daohang"] == expected
    assert expected == 90
    assert expected < settle.OVERFLOW_DAOHANG_WEEKLY_CAP


def test_羁绊过期任务_已挂入调度器():
    from bot import app as bot_app

    source = inspect.getsource(bot_app.main)

    assert "bonds_service.expire_pending" in source
    assert '"interval", hours=1' in source


def test_师父周活跃回报_已挂入周日错峰调度器():
    from bot import app as bot_app

    source = inspect.getsource(bot_app.main)

    assert "bonds_service.settle_weekly_mentor_activity" in source
    assert 'day_of_week="sun"' in source
    assert "minute=40" in source
