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


async def _插入羁绊(
    *,
    kind: str,
    a_id: int,
    b_id: int,
    status: str,
    created_at: int,
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
        "id", "kind", "a_id", "b_id", "status", "created_at", "expires_at",
        "activated_at", "dissolved_at", "active_days", "last_active_day",
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


def test_羁绊过期任务_已挂入调度器():
    from bot import app as bot_app

    source = inspect.getsource(bot_app.main)

    assert "bonds_service.expire_pending" in source
    assert '"interval", hours=1' in source
