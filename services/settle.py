from __future__ import annotations

"""惰性结算：精力恢复、闭关修为。纯函数，便于单测（spec §4）。"""

from config import realms as R

STAMINA_REGEN_SECONDS = R.STAMINA_REGEN_SECONDS[0]  # 炼气基线；其余境界见配置表
OFFLINE_CAP_HOURS = 12        # 闭关离线上限
# 气血/法力自然回复（#24）：按 max 的百分比/分，跨境界自动缩放。
# 0→满 所需秒数：气血 2000s(3%/分)、法力 1000s(6%/分，快于气血)。
HP_REGEN_SECONDS_PER_FULL = 2000
MP_REGEN_SECONDS_PER_FULL = 1000
HP_FLOOR_PCT = 0.20           # 活动结束写回的重伤地板：胜负都不破 20%·maxHP
# 每小阶目标时长改为按境界配置（见 config.realms.seclusion_stage_seconds，#15）。
# 保留此常量作为基线（筑基档 24h），仅供外部参考。
SECLUSION_STAGE_SECONDS = 24 * 3600
CULTIVATION_SCALE = 1_000_000
# 溢出转道行的转化率大幅下调（原 0.30/0.15）：满级挂机 100% 溢出，旧率把道行做成了
# 绕过「周封顶」设计的无限水管。改为小额转化，另配 OVERFLOW_DAOHANG_WEEKLY_CAP 周上限兜底。
DAOHANG_FULL_REALM_RATE = 0.08
DAOHANG_PRE_CAP_RATE = 0.03
# 溢出转道行的每周入账上限（跨顶点/次顶点圆满共用）。飞升点分支不在此约束内——它已被
# 独立的「每十万修为凝一点 + 每周 14 点」规则约束。
OVERFLOW_DAOHANG_WEEKLY_CAP = 600
# 道侣双修：只对重叠闭关秒数追加小幅闭关乘区，仍受调用方 SECLUSION clamp 截断。
PARTNER_SECLUSION_PCT = 0.05


def overflow_tier(realm: int, stage: int, now: int = None,
                  grace_until: int = 0) -> str:
    """返回当前溢出分流档位：full / grace_full / pre_cap / none。"""
    if realm == len(R.REALM_NAMES) - 1 and stage == R.num_stages(realm) - 1:
        return "full"
    if realm == len(R.REALM_NAMES) - 2 and stage == R.num_stages(realm) - 1:
        if now is not None and int(grace_until or 0) > int(now):
            return "grace_full"
        return "pre_cap"
    return "none"


def overflow_split(realm: int, stage: int, cur_cult: int, gain: int,
                   now: int = None, grace_until: int = 0) -> tuple[int, int, int]:
    """满级/准满级溢出修为分流，返回 (保留修为, 道行, 可凝点溢出修为)。

    - 当前最高大境界圆满：cultivation 封顶 advance_cost；越界 ×DAOHANG_FULL_REALM_RATE(0.08)→道行，
      全部越界修为交由飞升服务按定额、零头与周上限凝点。
    - 最高境界前一档圆满且仍在宽限期：临时按当前最高大境界圆满完整分流。
    - 最高境界前一档圆满且修为已满：越界 ×DAOHANG_PRE_CAP_RATE(0.03)→道行，不产飞升点。
    - 其它：原样累加，无转换。

    注：道行转化另受 OVERFLOW_DAOHANG_WEEKLY_CAP 周上限约束（在调用方 character.py 落地）。
    """
    cur_cult = max(0, int(cur_cult))
    gain = max(0, int(gain))
    total = cur_cult + gain
    tier = overflow_tier(realm, stage, now, grace_until)
    if tier in {"full", "grace_full"}:
        cap = R.advance_cost(realm, stage)
        overflow = max(0, total - cap)
        return min(total, cap), int(overflow * DAOHANG_FULL_REALM_RATE), overflow
    if tier == "pre_cap":
        cap = R.advance_cost(realm, stage)
        if cur_cult >= cap:
            overflow = max(0, total - cap)
            return min(total, cap), int(overflow * DAOHANG_PRE_CAP_RATE), 0
    return total, 0, 0


def overflow_to_daohang(realm: int, stage: int, cur_cult: int, gain: int,
                        now: int = None, grace_until: int = 0) -> tuple[int, int]:
    """满级/准满级溢出修为转道行，返回 (保留修为, 获得道行)。

    兼容包装：等价于 overflow_split 的前两元（不含飞升点）。新代码应直接用 overflow_split。
    """
    kept, daohang, _ = overflow_split(realm, stage, cur_cult, gain, now, grace_until)
    return kept, daohang


def stamina_regen_seconds(realm: int) -> int:
    """返回当前境界每恢复 1 点精力所需秒数。"""
    return R.STAMINA_REGEN_SECONDS.get(realm, STAMINA_REGEN_SECONDS)


def regen_stamina(stamina: int, stamina_at: int, cap: int, now: int,
                  realm: int = 0):
    """按时间戳惰性恢复精力，返回 (新精力, 新锚点时间戳)。"""
    if stamina >= cap:
        # 奖励精力允许无限超过上限；超限期间不恢复，也不积攒离线恢复进度。
        return stamina, now
    interval = stamina_regen_seconds(realm)
    gained = (now - stamina_at) // interval
    if gained <= 0:
        return stamina, stamina_at
    new_val = min(cap, stamina + gained)
    # 锚点只前移已消耗的整数刻度，避免丢失零头进度。
    new_at = stamina_at + gained * interval
    if new_val >= cap:
        new_at = now
    return new_val, new_at


def regen_resource(cur: int, cap: int, at: int, now: int, seconds_per_full: int):
    """按时间惰性回复气血/法力（#24），返回 (新值, 新锚点)。

    速率 = cap / seconds_per_full（点/秒），故跨境界随 max 缩放。仿 regen_stamina：
    锚点只前移「已消耗整点」对应的时间，避免快读时零头被反复丢弃导致永不回复。
    """
    if cap <= 0:
        return 0, now
    if cur >= cap:
        return cap, now
    gained = int((now - at) * cap / seconds_per_full)
    if gained <= 0:
        return cur, at
    new_val = min(cap, cur + gained)
    consumed = int(gained * seconds_per_full / cap)
    new_at = at + consumed
    if new_val >= cap:
        new_at = now
    return new_val, new_at


def seclusion_settle_window(start_at: int, now: int,
                            offline_cap_hours: int = OFFLINE_CAP_HOURS) -> tuple[int, int]:
    """返回实际结算闭关区间；必须先按离线上限截断，再参与后续交集计算。"""
    start_at = 0 if start_at is None else int(start_at)
    now = start_at if now is None else int(now)
    cap_seconds = int(max(0.0, float(offline_cap_hours)) * 3600)
    finish_at = min(now, start_at + cap_seconds)
    if finish_at < start_at:
        finish_at = start_at
    return start_at, finish_at


def overlap_seconds(first_start: int, first_end: int,
                    second_start: int, second_end: int) -> int:
    """两个半开时间区间的重叠秒数。"""
    start = max(int(first_start), int(second_start))
    finish = min(int(first_end), int(second_end))
    return max(0, finish - start)


def partner_seclusion_overlap_seconds(
        start_at: int,
        now: int,
        partner_start_at: int | None,
        partner_end_at: int | None = None,
        offline_cap_hours: int = OFFLINE_CAP_HOURS) -> int:
    """双修重叠秒数：本方与道侣区间均先按离线上限截断，再求交集。"""
    if partner_start_at is None:
        return 0
    own_start, own_end = seclusion_settle_window(start_at, now, offline_cap_hours)
    partner_finish = now if partner_end_at is None else partner_end_at
    partner_start, partner_end = seclusion_settle_window(
        partner_start_at, partner_finish, offline_cap_hours)
    return overlap_seconds(own_start, own_end, partner_start, partner_end)


def partner_seclusion_extra_units(realm: int, stage: int, overlap: int,
                                  root_bone: int = 0,
                                  partner_pct: float = PARTNER_SECLUSION_PCT) -> int:
    """道侣重叠秒数折算出的额外修为微单位。"""
    overlap = max(0, int(overlap or 0))
    partner_pct = max(0.0, float(partner_pct or 0.0))
    if overlap <= 0 or partner_pct <= 0:
        return 0
    return int(
        R.advance_cost(realm, stage)
        * overlap
        * (1 + max(0, root_bone) / 200)
        * partner_pct
        * CULTIVATION_SCALE
        / R.seclusion_stage_seconds(realm)
    )


def partner_seclusion_extra_gain(realm: int, stage: int, overlap: int,
                                 root_bone: int = 0,
                                 partner_pct: float = PARTNER_SECLUSION_PCT) -> int:
    """道侣重叠秒数折算出的额外修为整数值，供测试与文案展示。"""
    return partner_seclusion_extra_units(
        realm, stage, overlap, root_bone, partner_pct) // CULTIVATION_SCALE


def seclusion_gain(realm: int, stage: int, start_at: int, now: int,
                   root_bone: int = 0,
                   place_factor: float = 1.0,
                   offline_cap_hours: int = OFFLINE_CAP_HOURS) -> int:
    gain, _ = seclusion_gain_with_remainder(
        realm, stage, start_at, now, root_bone, place_factor, offline_cap_hours, 0)
    return gain


def seclusion_gain_with_remainder(realm: int, stage: int, start_at: int, now: int,
                                  root_bone: int = 0,
                                  place_factor: float = 1.0,
                                  offline_cap_hours: int = OFFLINE_CAP_HOURS,
                                  remainder_units: int = 0,
                                  activity_windows: list[tuple[int, int]] = None,
                                  active_factor: float = 1.0,
                                  partner_overlap_seconds: int = 0,
                                  partner_pct: float = 0.0) -> tuple[int, int]:
    """当前小阶 24 小时约得一级；根骨/外部加成再提速。"""
    settle_start, settle_finish = seclusion_settle_window(start_at, now, offline_cap_hours)
    effective_elapsed = _effective_elapsed(
        settle_start, settle_finish, activity_windows or [], active_factor)
    raw_units = int(
        R.advance_cost(realm, stage)
        * effective_elapsed
        * (1 + max(0, root_bone) / 200)
        * max(0.0, place_factor)
        * CULTIVATION_SCALE
        / R.seclusion_stage_seconds(realm)
    )
    partner_units = partner_seclusion_extra_units(
        realm, stage, partner_overlap_seconds, root_bone, partner_pct)
    total_units = raw_units + max(0, int(remainder_units or 0))
    total_units += partner_units
    return total_units // CULTIVATION_SCALE, total_units % CULTIVATION_SCALE


def _effective_elapsed(start_at: int, finish_at: int,
                       activity_windows: list[tuple[int, int]],
                       active_factor: float) -> float:
    total = max(0, finish_at - start_at)
    if total <= 0 or not activity_windows:
        return total
    active_factor = max(0.0, min(1.0, float(active_factor)))
    merged = []
    for raw_start, raw_finish in sorted(activity_windows):
        s = max(start_at, int(raw_start))
        f = min(finish_at, int(raw_finish))
        if f <= s:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], f))
        else:
            merged.append((s, f))
    active = sum(f - s for s, f in merged)
    return (total - active) + active * active_factor
