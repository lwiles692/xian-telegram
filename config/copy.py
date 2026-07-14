from __future__ import annotations

"""文案与 emoji —— 半文半白·正经仙侠。集中此处便于统一口吻。"""

E = {
    "sword": "⚔️", "pill": "💊", "stone": "🪙", "skill": "📖",
    "treasure": "🔮", "cultivate": "🧘", "boss": "🐲", "up": "📈",
    "bag": "🎒", "guide": "📜",
}

VERSION_NOTICE_TITLE = "📣 【三期·炼虚开放公告】"
OVERFLOW_NOTICE_TITLE = "🌌 【炼虚溢出分流】"

DAILY_AID_TEXT = {
    "化神丹": "凝婴问道补给：化神丹 ×1（绑定）。",
    "炼虚丹": "化神问虚补给：炼虚丹 ×1（绑定）。",
}

HELP_INTRO = "道友初入仙途，可循以下法门："
HELP_OUTRO = "大道三千，愿道友早证长生。"
HELP_GROUPS = (
    ("修行养成", (
        ("start", "踏入仙途 / 测灵根"),
        ("me", "查看道行"),
        ("cultivate", "闭关 / 出关"),
        ("daily", "每日签到"),
        ("quest", "悬赏任务"),
        ("bag", "储物袋"),
    )),
    ("历练斗法", (
        ("explore", "历练刷怪"),
        ("dungeon", "秘境副本"),
        ("pvp", "群内切磋"),
        ("rank", "天梯排行"),
        ("boss", "世界 Boss"),
        ("weekly", "周活动副本"),
    )),
    ("经营交易", (
        ("craft", "炼丹炼器"),
        ("skills", "法宝 / 功法"),
        ("shop", "NPC 商店"),
        ("market", "玩家坊市"),
        ("auction", "拍卖行"),
    )),
    ("宗门社交", (
        ("sect", "宗门"),
        ("master", "师徒"),
        ("partner", "道侣共修"),
        ("path", "道途 / 转修"),
        ("ascension", "飞升试炼"),
        ("sectwar", "宗门战据点"),
        ("help", "重览此卷"),
    )),
)
