from __future__ import annotations

"""拍卖行配置（spec-v3 §6 / M2）。"""

AUCTION_DURATION_SECONDS = 24 * 3600
MIN_BID_INCREMENT_PCT = 0.05
SNIPE_WINDOW_SECONDS = 5 * 60
SNIPE_EXTEND_SECONDS = 5 * 60
SNIPE_MAX_EXTENSIONS = 6
LISTING_FEE_RATE = 0.01
AUCTION_TAX_RATE = 0.10
MAX_ACTIVE_AUCTIONS_PER_SELLER = 3
BUYOUT_MIN_MULTIPLIER = 1.20
HIGH_PRICE_BROADCAST_THRESHOLD = 1_000_000
AUCTION_BROADCAST_WINDOW_SECONDS = 3600
AUCTION_BROADCAST_LIMIT = 10
CLOSING_NOTICE_WINDOW_SECONDS = 3600
WATCHER_NOTIFY_LIMIT = 50
AUDIT_FREQUENT_WINDOW_SECONDS = 24 * 3600
AUDIT_FREQUENT_MIN_TRADES = 3

KIND_EQUIPMENT = "equipment"
KIND_MATERIAL = "material"
AUCTION_KINDS = frozenset({KIND_EQUIPMENT, KIND_MATERIAL})

STATUS_ACTIVE = "active"
STATUS_SOLD = "sold"
STATUS_PASSED = "passed"
STATUS_CANCELLED = "cancelled"
AUCTION_STATUSES = frozenset({STATUS_ACTIVE, STATUS_SOLD, STATUS_PASSED, STATUS_CANCELLED})

INSTANCE_STATUS_NORMAL = "normal"
INSTANCE_STATUS_AUCTION = "auction"
INSTANCE_STATUSES = frozenset({INSTANCE_STATUS_NORMAL, INSTANCE_STATUS_AUCTION})

SYSTEM_FLOOR_PRICE_BY_TIER = {
    "凡": 50,
    "灵": 200,
    "宝": 800,
    "玄": 3000,
}
DEFAULT_SYSTEM_FLOOR_PRICE = 100

MATERIAL_WHITELIST = frozenset({
    "星陨砂", "幽都魂晶", "天外残玉",
    "雾泽虚砂", "裂海空髓", "混沌残核",
})
MATERIAL_MARKET_VALUE_MULTIPLIER = 3.0


def floor_price_for_tier(tier: str) -> int:
    """按品阶取系统底价。"""
    return SYSTEM_FLOOR_PRICE_BY_TIER.get(tier, DEFAULT_SYSTEM_FLOOR_PRICE)


def min_buyout_price(start_price: int) -> int:
    """一口价下限：起拍价 ×1.2，向上取整。"""
    return int(start_price * BUYOUT_MIN_MULTIPLIER + 0.999999)


def listing_fee(start_price: int) -> int:
    """挂拍费：起拍价 1%，至少 1 灵石。"""
    return max(1, int(start_price * LISTING_FEE_RATE))


def min_next_bid(current_bid: int) -> int:
    """下一口最低出价：当前价至少加 5%，向上取整。"""
    return int(current_bid * (1 + MIN_BID_INCREMENT_PCT) + 0.999999)
