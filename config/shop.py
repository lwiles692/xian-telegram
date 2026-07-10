"""NPC 商店与回收配置（spec §9）。"""
from __future__ import annotations

SHOP_ITEMS = {
    "灵草": {"price": 12, "realm": 0},
    "玄铁矿": {"price": 24, "realm": 1},
    "兽皮": {"price": 16, "realm": 0},
    "妖丹": {"price": 55, "realm": 1},
    # 基础恢复丹（#28）：填补筑基前的回血/回蓝补给断层。炼气期还不能自炼（配方 realm≥1）、
    # 收入也薄，故标 qi_half 在筑基前半价；筑基后恢复全价，且 /craft 自炼更省，引导转向自炼。
    "疗伤丹": {"price": 50, "realm": 0, "qi_half": True},
    "补灵丹": {"price": 60, "realm": 0, "qi_half": True},
    "虎力丹": {"price": 120, "realm": 0},
    "凝神丹": {"price": 120, "realm": 0},
    "筑基丹": {"price": 260, "realm": 0},
    "金丹": {"price": 900, "realm": 1},
    "元婴丹": {"price": 2400, "realm": 2},
    "洗髓丹": {"price": 900, "realm": 2},
    "玄铁剑图纸": {"price": 220, "realm": 1},
    "青木甲图纸": {"price": 260, "realm": 1},
    "洗髓丹丹方": {"price": 420, "realm": 2},
    "聚灵佩图纸": {"price": 460, "realm": 2},
}


FOUNDATION_REALM = 1  # realm 索引：0=炼气，1=筑基（见 config.realms）。


def shop_price(item_key: str, realm: int) -> int:
    """按境界取商店价：标 ``qi_half`` 的物品在筑基前（炼气期）半价（向上取整）。"""
    good = SHOP_ITEMS.get(item_key)
    if not good:
        return 0
    price = good["price"]
    if good.get("qi_half") and realm < FOUNDATION_REALM:
        return (price + 1) // 2
    return price


def goods_for_realm(realm: int):
    return [(key, val) for key, val in SHOP_ITEMS.items() if realm >= val["realm"]]


# 灵石买精力（#16）：按境界基价 + 当日第 n 次翻倍递增 + 每日封顶，
# 让首买单价就高于当前最佳内容的灵石/精力产出，堵死 灵石→精力→刷钱 套利。
STAMINA_BUY_BASE = {0: 120, 1: 260, 2: 600, 3: 1200, 4: 2800, 5: 6000}
STAMINA_BUY_DAILY_LIMIT = 3
STAMINA_BUY_GAIN = 20


def stamina_buy_cost(realm: int, nth: int) -> int:
    """当日第 nth 次（1-indexed）买精力的灵石价：基价 × 2^(n-1)。"""
    base = STAMINA_BUY_BASE.get(realm, STAMINA_BUY_BASE[max(STAMINA_BUY_BASE)])
    return base * (2 ** max(0, nth - 1))
