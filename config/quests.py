from __future__ import annotations

"""悬赏任务与成就配置。数值初版可调。"""

ONBOARDING_WINDOW_DAYS = 7

ONBOARDING_QUESTS = {
    "onboarding_daily": {
        "name": "初问山门",
        "period": "onboarding",
        "unlock_day": 1,
        "event": "daily.checkin",
        "target": 1,
        "reward": {"stone": 80, "stamina": 20, "bound_items": {"疗伤丹": 1}},
    },
    "onboarding_explore": {
        "name": "初试锋芒",
        "period": "onboarding",
        "unlock_day": 1,
        "event": "explore.win",
        "target": 1,
        "reward": {"stone": 100, "bound_items": {"补灵丹": 1}},
    },
    "onboarding_craft": {
        "name": "炉前识火",
        "period": "onboarding",
        "unlock_day": 2,
        "event": "craft.done",
        "target": 1,
        "reward": {"stone": 120, "bound_items": {"灵草": 3, "玄铁矿": 2}},
    },
    "onboarding_dungeon": {
        "name": "探幽入境",
        "period": "onboarding",
        "unlock_day": 3,
        "event": "dungeon.clear",
        "target": 1,
        "reward": {"stone": 140, "stamina": 20, "bound_items": {"妖丹": 1}},
    },
    "onboarding_pvp": {
        "name": "论道初胜",
        "period": "onboarding",
        "unlock_day": 4,
        "event": "pvp.win",
        "target": 1,
        "reward": {"stone": 160, "bound_items": {"虎力丹": 1}},
    },
    "onboarding_market": {
        "name": "坊市试摊",
        "period": "onboarding",
        "unlock_day": 5,
        "event": "market.list",
        "target": 1,
        "reward": {"stone": 160, "bound_items": {"凝神丹": 1}},
    },
    "onboarding_sect": {
        "name": "拜入宗门",
        "period": "onboarding",
        "unlock_day": 6,
        "event": "sect.join",
        "target": 1,
        "reward": {"stone": 180, "stamina": 20, "bound_items": {"天材地宝": 1}},
    },
    "onboarding_boss": {
        "name": "合击妖王",
        "period": "onboarding",
        "unlock_day": 7,
        "event": "world_boss.challenge",
        "target": 1,
        "reward": {"stone": 220, "bound_items": {"筑基丹": 1}},
    },
}

QUESTS = {
    **ONBOARDING_QUESTS,
    "daily_explore": {
        "name": "巡山斩妖",
        "period": "daily",
        "event": "explore.win",
        "target": 3,
        "reward": {"stone": 120},
    },
    "daily_craft": {
        "name": "炉火不息",
        "period": "daily",
        "event": "craft.done",
        "target": 1,
        "reward": {"stone": 80},
    },
    "daily_pvp_win": {
        "name": "一战扬名",
        "period": "daily",
        "event": "pvp.win",
        "target": 1,
        "reward": {"stone": 100},
    },
    "weekly_dungeon": {
        "name": "秘境探幽",
        "period": "weekly",
        "event": "dungeon.clear",
        "target": 3,
        "reward": {"stone": 500, "items": {"妖丹": 3}},
    },
    "weekly_boss": {
        "name": "合力诛妖",
        "period": "weekly",
        "event": "world_boss.challenge",
        "target": 5,
        "reward": {"stone": 360, "items": {"妖丹": 2}},
    },
}

ACHIEVEMENTS = {
    "first_jindan": {
        "name": "金丹初成",
        "event": "breakthrough.big_success",
        "min_target_realm": 2,
        "reward": {"stone": 300},
    },
    "first_yuanying": {
        "name": "元婴出窍",
        "event": "breakthrough.big_success",
        "min_target_realm": 3,
        "reward": {"stone": 1000},
    },
    "first_boss": {
        "name": "初斩妖王",
        "event": "explore.boss_win",
        "reward": {"stone": 160},
    },
    "first_pvp_win": {
        "name": "天梯首胜",
        "event": "pvp.win",
        "reward": {"stone": 120},
    },
    "first_dungeon_clear": {
        "name": "秘境通关",
        "event": "dungeon.clear",
        "reward": {"stone": 220},
    },
}
