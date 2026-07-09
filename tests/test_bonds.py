from __future__ import annotations

import inspect
import sqlite3

import pytest
import pytest_asyncio

from config import realms as R
from models import db
from services import character


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


@pytest.mark.asyncio
async def test_羁绊_schema_重复开库仍成阵(tmp_path):
    path = str(tmp_path / "bonds-schema.db")
    await db.init_db(path)
    await db.init_db(path)
    try:
        bond_cols = await _列字典("social_bonds")
        milestone_cols = await _列字典("bond_milestones")
        indexes = await _索引字典("social_bonds")
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

    assert {"idx_bonds_mentor_b", "idx_bonds_partner_a", "idx_bonds_pending_expire",
            "idx_bonds_a", "idx_bonds_b"} <= set(indexes)
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


def test_羁绊常量_四十八时辰与七日法度():
    from config import bonds as BONDS

    assert BONDS.PENDING_EXPIRE_SECONDS == 48 * 3600
    assert BONDS.DISSOLVE_COOLDOWN_SECONDS == 7 * 24 * 3600
    assert BONDS.MAX_ACTIVE_DISCIPLES == 3
    assert BONDS.KIND_MENTOR == "mentor"
    assert BONDS.KIND_PARTNER == "partner"


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


def test_羁绊过期任务_已挂入调度器():
    from bot import app as bot_app

    source = inspect.getsource(bot_app.main)

    assert "bonds_service.expire_pending" in source
    assert '"interval", hours=1' in source
