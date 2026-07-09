from __future__ import annotations

"""师徒 / 道侣关系配置（spec-v3 §4 / M3）。"""

KIND_MENTOR = "mentor"
KIND_PARTNER = "partner"
BOND_KINDS = frozenset({KIND_MENTOR, KIND_PARTNER})

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DISSOLVED = "dissolved"
STATUS_DECLINED = "declined"
STATUS_EXPIRED = "expired"
BOND_STATUSES = frozenset({
    STATUS_PENDING,
    STATUS_ACTIVE,
    STATUS_DISSOLVED,
    STATUS_DECLINED,
    STATUS_EXPIRED,
})

PENDING_EXPIRE_SECONDS = 48 * 3600
DISSOLVE_COOLDOWN_SECONDS = 7 * 24 * 3600
MAX_ACTIVE_DISCIPLES = 3

# T3.2/T3.5：师父至少元婴，徒弟至多筑基圆满；服务层统一读取，避免各处自解。
MENTOR_MIN_REALM = 3
DISCIPLE_MAX_REALM = 1

# T3.3：出师前 active 徒弟闭关效率 +5%，并入 SECLUSION clamp，不提高总上限。
DISCIPLE_SECLUSION_PCT = 0.05

# T3.3：师父每日传功给徒弟的小额修为；均低于同境界初期 1 小时普通闭关收益的 50%。
MENTOR_TRANSFER_CULTIVATION_BY_REALM = {
    0: 5,
    1: 12,
    2: 60,
    3: 300,
}
