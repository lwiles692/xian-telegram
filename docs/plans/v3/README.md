# 《问道》三期执行计划(基于 spec-v3 审查)

> 本目录是 [`spec-v3.md`](../../../spec-v3.md) 的落地执行计划。
> spec 负责"做什么 / 为什么",本目录负责"按什么顺序、改哪些文件、验收标准是什么"。
> 实施前如需调整设计,先改 `spec-v3.md`,再据此更新本目录。

基线:`v0.3` 分支,`python -m pytest` **304 passed**(2026-07-08 实测)。
所有计划的总验收前提:**新增内容不破坏现存 304 个测试**。

---

## 0. 审查结论:spec-v3 与代码核对

下列结论均已对照 `v0.3` 真实代码核对(非纸面推断)。

### A. 核对通过项(作为设计地基)

- `next_stage` / `is_big_breakthrough` 判据是 `realm+1 < len(REALM_NAMES)`(`config/realms.py:84-91`)——
  往 `REALM_NAMES` 追加"炼虚期"+ 各配置 dict 补 `[5]`,化神圆满自动翻成大突破节点,无需改突破服务逻辑。
  与 v2 同一接驳点 ✓。
- `overflow_split` 判据同样 len-based(`services/settle.py:41,46`),spec §3.8"追加 realm 5 即生效"成立;
  现行比率 0.08 / 0.20 / 0.03 与 spec §1 表格一致 ✓。`OVERFLOW_DAOHANG_WEEKLY_CAP=600` 在
  `services/character.py:_cap_overflow_daohang` 落地 ✓。
- `BIG_BREAKTHROUGH` 以**目标境界索引**为键(`config/realms.py:19`),spec 写 `BIG_BREAKTHROUGH[5]` 一致 ✓。
- balance_sim 报告循环已全部是 `len(REALM_NAMES)` 驱动(`tools/balance_sim.py:327,391,401`),
  无 v2 时期的 `range(4)` 硬编码;追加 realm 5 报告自动覆盖 ✓。
- 天劫状态机按 `target_realm` 分流已有先例(`services/breakthrough.py:84`:神魂劫 vs 雷劫)——
  虚空劫 = 再加一档选项/文案,无需加表 ✓。
- 残方合成有现成管线:`config/recipes.py:107` 的 recipe key `huashen_pill`
  (`化神丹残方×6+妖丹×4→化神丹`);炼虚丹复用该管线,但材料配比按 spec §3.4 的
  `炼虚丹残方×4`,非照搬化神丹的 `×6+妖丹×4`,并加产物绑定。
- 满淬炼档已进 balance_sim(`DAO_MAX_REFINED_PROFILES`,`tools/balance_sim.py:50)——
  §1.1 收口项 2 实际只差"化神圆满满 buff **组合档**",工作量小于 spec 预估。
- 满 buff 档做法有先例:`YUANYING_FULL_BUFF`(`tools/balance_sim.py:41`)用 `extra_pct` 直接推到
  clamp 上限,化神满 buff 档沿用同一手法即可(clamp 保证等价于逐项叠满)。
- `config/quests.py` 的 `period/event/target/reward` 管线可直接承载七日引导任务链(M3),无需新任务框架。

### B. 必须修正 / 实施注意(spec 表述与代码不符)

1. **模块命名冲突(评审已确认,spec §8.1 已回改为 `config.bonds`,2026-07-08)**:原 spec 写
   `config.social`,但 `config/social.py` + `services/social.py` 已被 v2 群播报/DM 通知占用。
   师徒/道侣落到**新模块 `config/bonds.py` + `services/bonds.py` + `handlers/bonds.py`**。
2. **spec §5.2 落库表述已回改(2026-07-08)**:`characters` 只有 `seclusion_at`(开始,0=未闭关,
   `models/db.py:37`),**没有已结束闭关的区间**——原文"起止时间戳现已落库"不准确,已改为
   "进行中闭关的开始时间戳已落库"。实现一律以 §8.2 的 `last_seclusion_start/end` 为准。
3. **失败累计保底要动 `big_success_rate` 调用链**:`big_success_rate(realm, root_bone, pill_bonus)`
   (`services/breakthrough.py:24`)无保底概念。在调用点(`services/breakthrough.py:139`)按
   `char["realm"]==4` 叠加 `big_fail_streak×10%`,不改低境界路径(spec §8.2 字段边界注释照抄进代码)。
4. **`NO_TRADE` 名单**(`config/items.py:91`)需加 `炼虚丹`;拍卖行禁拍校验复用同一 frozenset +
   `bound=1` 双重判断,不另建名单。
5. **`config.tribulation` 不新建文件(spec §8.1 已回改为 `config.events`,2026-07-08)**:
   现有天劫选项(`TRIBULATION_ACTIONS` / `SHENHUN_TRIBULATION_ACTIONS`)在 `config/events.py`,
   心魔劫选项与参数落同一处。

### C. 迁移触点清单(漏改即运行时 KeyError / 验收缺档)

| 触点 | 改动 |
|---|---|
| `config/realms.py` | `REALM_NAMES`、`REALM_STAGES`、`BIG_BREAKTHROUGH`、`_REALM_BASE_COST`、`_ANCHORS`、`STAMINA_CAP`、`SECLUSION_STAGE_HOURS` 七个 dict 补 `[5]`(`STAMINA_CAP` 有 6 处直接索引:`services/character.py:74,259,293`、`services/shop.py:95`、`handlers/explore.py:54`、`handlers/me.py:29`) |
| `config/shop.py` | `STAMINA_BUY_BASE[5] = 6000` |
| `config/bosses.py` | `_REALM_TIER[5] = "lianxu"`(M1;spec §3.7 未列,v2 审查 C-6 同款遗漏) |
| `tools/balance_sim.py` | `CONTENT_REALM`(line 56)加三张炼虚图 + 虚空神殿档位 |
| `tests/test_balance.py` 等 | grep `range(`、境界档位断言,同步到 `len(REALM_NAMES)` |
| `models/db.py` | 新增 `game_flags` kv 表(现无等价物);各 `_ensure_column` 见各里程碑 |

---

## 1. 跨里程碑架构约束(所有里程碑共同遵守)

| 约束 | 来源 | 落地方式 |
|---|---|---|
| 反套利红线:新内容灵石/精力产出 < 当日首买成本(炼虚 300)至少 25% | spec §3.5 / §6.5 | 每个产出内容进 `tools/balance_sim` 套利校验 + `tests/test_economy.py` |
| 一切新增百分比加成进现有 clamp(ATTACK/SURVIVAL 0.25、SECLUSION 0.60),禁止旁路 | spec §0.4 | 传承/双修/道心通明/本命全部走 `config/buffs.py` 合算管线;clamp 测试全量回归 |
| clamp 截断透明化:被截断时收功文案显示"已达闭关增益上限" | spec §4.3 / §5.2 | 收功文案统一处理,师徒/道侣共用 |
| 一次性 token + 原子事务:结契/拜师/出师/出价/结算 | spec §1 | `callback_tokens` + `db.transaction()`(`BEGIN IMMEDIATE`) |
| 领域事件播报:炼虚突破/出师/结契/天价成交 | spec §1 | `game_events.emit_conn` |
| 新前台动作记 `activity_windows`,勿复用 `reserve_stamina_for_action`(它拒绝闭关中行动) | spec §1 | 共修仪式等仿 `services/activity.record_window` |
| 存档不重置:schema 全部 `_ensure_column` 幂等或独立可重入迁移 | spec §0.10 / §8 | 旧档回填默认值 |
| 战斗门槛用"可刷 / 门槛"口径,不写字面胜率 | spec §1 | 验收断言按挑战成功率 <5% / 稳定可刷描述 |
| **周事件总量审计**:新增周期性必做事件必须同步降级/合并旧事件或明确"可错过无惩罚" | spec §9 | 每里程碑 DoD 附"活跃玩家周必做清单 + 预估耗时"审计表 |

---

## 2. 里程碑总览

| 里程碑 | 计划文件 | 核心交付 | 是否阻塞下一步 |
|---|---|---|---|
| **M0 炼虚开放** | [v3-m0-lianxu-open.md](v3-m0-lianxu-open.md) | v2 收口(#45、化神满 buff 档)→ 炼虚配置、炼虚丹(残方+失败保底)、三图、虚空劫、溢出上移+宽限期、公告、M1 埋点 | 是(其余全部依赖) |
| **M1 完整链路+心魔劫** | [v3-m1-lianxu-loop.md](v3-m1-lianxu-loop.md) | 虚空神殿、炼虚 Boss、炼虚装备/炼制链、LIANXU_GEARED 回归、心魔劫选项 | 否 |
| **M2 拍卖行** | [v3-m2-auction.md](v3-m2-auction.md) | 英式拍卖+buyout、escrow 实扣、防狙击、实例托管、幂等结算、审计、曝光 | 否(独立开发独立验收) |
| **M3 师徒+引导** | [v3-m3-mentor-onboarding.md](v3-m3-mentor-onboarding.md) | `social_bonds`/`bond_milestones`、拜师/出师、传功、周活跃回报、桃李称号、七日引导 | 否 |
| **M4 道侣+共修** | [v3-m4-partner-ritual.md](v3-m4-partner-ritual.md) | 结契/解除、双修重叠折算、互赠、周双人任务、同步共修仪式(覆盖师徒/道侣) | 否 |
| **M5 本命法宝雏形** | [v3-m5-natal-outline.md](v3-m5-natal-outline.md) / [detail](v3-m5-natal-detail.md) | 认主/解缚、喂养成长、器修协同、clamp/交易隔离回归 | 否 |

**推荐实施顺序**:M0(收口两项最先)→ M1 → M2 → M3 → M4 → M5。

- M2 拍卖行独立开发独立验收,不与炼虚链路混做;M2 上线前白名单材料走坊市过渡(spec §6.1)。
- M3 / M4 可互换;若互换,**同步共修仪式挪进后上线的那个里程碑**(它要求 `social_bonds` 两种 kind 都已存在)。
- M4 双修依赖 M3 落的 `social_bonds` 表结构(partner 镜像双行索引在建表时一并建好,避免二次迁移)。
