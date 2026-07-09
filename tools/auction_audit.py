from __future__ import annotations

"""输出拍卖行高价与高频互拍审计报告。"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import auction as auction_config
from models import db
from services import auction


def resolve_db_arg(raw: str | None) -> str | None:
    if raw is None:
        return None
    path = Path(raw).expanduser()
    if not path.exists():
        raise SystemExit(f"数据库不存在：{path}")
    if path.is_dir():
        raise SystemExit(f"数据库路径是目录：{path}")
    return str(path.resolve())


async def _main() -> None:
    parser = argparse.ArgumentParser(description="巡检拍卖行高价成交与高频互拍。")
    parser.add_argument("--db", help="SQLite 数据库路径；默认使用应用数据库。")
    parser.add_argument(
        "--limit-price", type=int,
        default=auction_config.HIGH_PRICE_BROADCAST_THRESHOLD)
    parser.add_argument(
        "--window-seconds", type=int,
        default=auction_config.AUDIT_FREQUENT_WINDOW_SECONDS)
    parser.add_argument(
        "--min-trades", type=int,
        default=auction_config.AUDIT_FREQUENT_MIN_TRADES)
    parser.add_argument("--now", type=int)
    args = parser.parse_args()

    await db.init_db(resolve_db_arg(args.db))
    try:
        report = await auction.audit_report(
            limit_price=args.limit_price,
            now=args.now,
            window_seconds=args.window_seconds,
            min_trades=args.min_trades)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(_main())
