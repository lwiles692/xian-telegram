"""轻量可玩事件配置：历练奇遇与渡劫应对。"""
from __future__ import annotations

ENCOUNTER_RATE = 0.12

ENCOUNTERS = {
    "cliff_cave": {
        "title": "坠崖洞府",
        "text": "山雾忽裂，崖下隐见一处残破洞府，灵光明灭。",
        "choices": {
            "probe": {
                "label": "探入洞府",
                "text": "道友冒险探入洞府，险中取宝。",
                "reward_mult": 1.40,
                "drop_bonus": 0.25,
                "hazard_hp_pct": 0.18,
            },
            "detour": {
                "label": "绕行",
                "text": "道友按原路稳步历练，不贪此险。",
                "reward_mult": 1.00,
                "drop_bonus": 0.0,
                "hazard_hp_pct": 0.0,
            },
            "rescue": {
                "label": "救人",
                "text": "道友救下一名同道，分出些许精力相助。",
                "reward_mult": 0.75,
                "drop_bonus": 0.0,
                "hazard_hp_pct": 0.0,
                "contribution": 5,
            },
        },
    },
}

TRIBULATION_ACTIONS = {
    "artifact": {
        "label": "护体法宝",
        "shield": 180,
        "heal_pct": 0.0,
        "item": None,
        "text": "祭起护体法宝，青光挡下一截雷威。",
    },
    "skill": {
        "label": "护盾战技",
        "shield": 120,
        "heal_pct": 0.0,
        "item": None,
        "text": "运转护盾战技，以法力硬接天雷。",
    },
    "pill": {
        "label": "嗑大还丹",
        "shield": 40,
        "heal_pct": 0.35,
        "item": "大还丹",
        "text": "吞下一枚大还丹，药力护住心脉。",
    },
    "endure": {
        "label": "硬抗",
        "shield": 0,
        "heal_pct": 0.0,
        "item": None,
        "text": "不借外物，凝神硬抗雷劫。",
    },
}

SHENHUN_TRIBULATION_ACTIONS = {
    "focus": {
        "label": "凝神守一",
        "shield": 220,
        "heal_pct": 0.0,
        "item": None,
        "text": "凝神守一，紧闭识海，化去一缕心魔侵扰。",
    },
    "artifact": {
        "label": "祭出护体法宝",
        "shield": 300,
        "heal_pct": 0.0,
        "item": None,
        "text": "祭出护体法宝，灵光护住神魂。",
    },
    "pill": {
        "label": "服大还丹",
        "shield": 80,
        "heal_pct": 0.45,
        "item": "大还丹",
        "text": "服下一枚大还丹，药力稳住翻涌气血。",
    },
}

XUKONG_TRIBULATION_ACTIONS = {
    "source": {
        "label": "凝守本源",
        "shield": 260,
        "heal_pct": 0.0,
        "item": None,
        "text": "凝守本源，任虚空裂隙刮骨，不令元神离位。",
    },
    "artifact": {
        "label": "祭护体法宝",
        "shield": 360,
        "heal_pct": 0.0,
        "item": None,
        "text": "祭起护体法宝，玄光护住肉身，不坠虚无。",
    },
    "pill": {
        "label": "服大还丹",
        "shield": 120,
        "heal_pct": 0.45,
        "item": "大还丹",
        "text": "服下一枚大还丹，药力续住崩裂经脉。",
    },
}
