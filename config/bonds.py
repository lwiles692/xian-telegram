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
