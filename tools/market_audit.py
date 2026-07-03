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


async def _main():
    parser = argparse.ArgumentParser(description="Audit player market listings.")
    parser.add_argument("--db", help="SQLite database path; defaults to the app database.")
    parser.add_argument("--limit-price", type=int, default=1_000_000)
    parser.add_argument("--window-seconds", type=int, default=market.AUDIT_FREQUENT_WINDOW_SECONDS)
    parser.add_argument("--min-trades", type=int, default=market.AUDIT_FREQUENT_MIN_TRADES)
    parser.add_argument("--now", type=int)
    args = parser.parse_args()

    await db.init_db(args.db)
    try:
        report = {
            "high_price": await market.audit_suspicious(args.limit_price),
            "frequent_trades": await market.audit_frequent_trades(
                now=args.now,
                window_seconds=args.window_seconds,
                min_trades=args.min_trades),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(_main())
