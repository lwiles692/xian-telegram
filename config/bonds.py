from __future__ import annotations

"""师徒 / 道侣关系配置（spec-v3 §4 / §5）。"""

KIND_MENTOR = "mentor"
KIND_PARTNER = "partner"
BOND_KINDS = frozenset({KIND_MENTOR, KIND_PARTNER})

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DISSOLVED = "dissolved"
STATUS_DECLINED = "declined"
STATUS_EXPIRED = "expired"
STATUS_GRADUATED = "graduated"
BOND_STATUSES = frozenset({
    STATUS_PENDING,
    STATUS_ACTIVE,
    STATUS_DISSOLVED,
    STATUS_DECLINED,
    STATUS_EXPIRED,
    STATUS_GRADUATED,
})

PENDING_EXPIRE_SECONDS = 48 * 3600
DISSOLVE_COOLDOWN_SECONDS = 7 * 24 * 3600
MAX_ACTIVE_DISCIPLES = 3

# T3.2/T3.5：师父至少元婴，徒弟至多筑基圆满；服务层统一读取，避免各处自解。
MENTOR_MIN_REALM = 3
DISCIPLE_MAX_REALM = 1

# T4.1：道侣结契门槛与消耗。服务层后续只读这些常量，避免各处自解。
PARTNER_MIN_REALM = 2
PARTNER_TOKEN_ITEM = "同心结"
PARTNER_KNOT_ITEM = PARTNER_TOKEN_ITEM
PARTNER_DISSOLVE_STONE_COST = 50_000

# T4.2：双修只占闭关增益切片，后续接入 SECLUSION clamp。
PARTNER_SECLUSION_PCT = 0.05

# T3.3：出师前 active 徒弟闭关效率 +5%，并入 SECLUSION clamp，不提高总上限。
DISCIPLE_SECLUSION_PCT = 0.05

# T3.3：师父每日传功给徒弟的小额修为；均低于同境界初期 1 小时普通闭关收益的 50%。
MENTOR_TRANSFER_CULTIVATION_BY_REALM = {
    0: 5,
    1: 12,
    2: 60,
    3: 300,
}

# T3.5：出师双条件；锚定“最高活跃档到元婴初期约 8 天”，成长曲线调整时随之重算。
GRADUATION_ACTIVE_DAYS_REQUIRED = 8
GRADUATION_MIN_REALM = 3

MENTOR_MILESTONE_REWARDS = {
    "jindan": {"target_realm": 2, "daohang": 30},
    "yuanying": {"target_realm": 3, "daohang": 80},
}

GRADUATION_MILESTONE = "graduate"
GRADUATION_MENTOR_DAOHANG = 120
GRADUATION_DISCIPLE_DAOHANG = 60
GRADUATION_BOUND_ITEMS = {"天材地宝": 1, "妖丹": 3}

MENTOR_TITLE_THRESHOLDS = (
    (1, "授业真人"),
    (3, "桃李盈门"),
    (5, "一代宗师"),
)

# T3.6：师父周活跃回报；按徒弟本周活跃日计，小额并入溢出道行周上限。
MENTOR_WEEKLY_DAOHANG_PER_ACTIVE_DAY = 5
MENTOR_WEEKLY_DAOHANG_CAP_PER_DISCIPLE = 30

# T3.7：徒弟完成七日引导时的师徒联动小额奖励，跟教学行为直接绑定。
ONBOARDING_DISCIPLE_LINK_REWARD = {"stone": 40, "bound_items": {"疗伤丹": 1}}
ONBOARDING_MENTOR_LINK_REWARD = {"stone": 40}

# T4.3：道侣每日互赠白名单；赠出后仍为绑定，只允许低套利空间的丹药 / 材料。
PARTNER_DAILY_GIFT_QTY = 1
PARTNER_DAILY_GIFT_WHITELIST = frozenset({
    "疗伤丹",
    "补灵丹",
    "大还丹",
    "虎力丹",
    "凝神丹",
    "灵草",
    "玄铁矿",
    "兽皮",
    "妖丹",
    "天材地宝",
})


def is_partner_gift_allowed(item_key: str) -> bool:
    return item_key in PARTNER_DAILY_GIFT_WHITELIST
