"""Print market audit rows for high-price and frequent trades."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import db
from services import market


def resolve_db_arg(raw: str | None) -> str | None:
    if raw is None:
        return None
    path = Path(raw).expanduser()
    if not path.exists():
        raise SystemExit(f"database does not exist: {path}")
    if path.is_dir():
        raise SystemExit(f"database path is a directory: {path}")
    return str(path.resolve())


async def _main():
    parser = argparse.ArgumentParser(description="Audit player market listings.")
    parser.add_argument("--db", help="SQLite database path; defaults to the app database.")
    parser.add_argument("--limit-price", type=int, default=1_000_000)
    parser.add_argument("--window-seconds", type=int, default=market.AUDIT_FREQUENT_WINDOW_SECONDS)
    parser.add_argument("--min-trades", type=int, default=market.AUDIT_FREQUENT_MIN_TRADES)
    parser.add_argument("--now", type=int)
    args = parser.parse_args()

    await db.init_db(resolve_db_arg(args.db))
    try:
        report = await market.audit_report(
            limit_price=args.limit_price,
            now=args.now,
            window_seconds=args.window_seconds,
            min_trades=args.min_trades)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(_main())
