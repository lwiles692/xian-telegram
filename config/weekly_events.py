from __future__ import annotations

"""周活动副本配置（v2 M4 / spec-v3 T4.4）。"""

WEEKLY_DAOHANG_CAP = 300
RUN_DAOHANG_REWARD = 120
RUN_STAMINA_COST = 40
RUN_DURATION_SECONDS = 20 * 60
ACTIVITY_MATERIAL = "天魔令"
PARTNER_WEEKLY_TASK_DAOHANG = 30

WEEKLY_THEMES = {
    "tianmo": {"name": "天魔潮", "material": ACTIVITY_MATERIAL},
    "danxia": {"name": "丹霞会", "material": "丹霞玉"},
    "wanjian": {"name": "万剑冢", "material": "剑冢铁"},
}

# 活动材料（三周主题产出）——只可在活动商店消耗，不入坊市（绑定）。
ACTIVITY_MATERIALS = ["天魔令", "丹霞玉", "剑冢铁"]

# 活动商店兑换出口（spec §5.4 / T4.1）：消耗活动材料换绑定道具 / 飞升点。
# material_cost 为「任意活动材料」的数量；reward_kind='item' 发绑定道具，'ascension' 发飞升点。
SHOP_OFFERS = {
    "baoming": {"name": "保命符", "reward_kind": "item", "reward_item": "保命符",
                "reward_qty": 1, "material_cost": 2},
    "switch_token": {"name": "转修令", "reward_kind": "item", "reward_item": "转修令",
                     "reward_qty": 1, "material_cost": 4},
    "path_material": {"name": "天外残玉", "reward_kind": "item", "reward_item": "天外残玉",
                      "reward_qty": 1, "material_cost": 5},
    "heart_knot": {"name": "同心结", "reward_kind": "item", "reward_item": "同心结",
                   "reward_qty": 1, "material_cost": 6},
    "ascension": {"name": "飞升点", "reward_kind": "ascension",
                  "reward_qty": 1, "material_cost": 3},
}
