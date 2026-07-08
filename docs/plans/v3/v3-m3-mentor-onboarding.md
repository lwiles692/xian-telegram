# V3-M3 师徒 + 新角色引导

> 对应 spec-v3 §4、§5.5(状态机)、§8.2、§10。
> 目标:新角色承接(拜师/传功/引导任务链)+ 高境界传承收益(出师/周活跃回报/桃李称号)。
> 前置:无硬依赖(可与 M2 并行)。M3/M4 可互换;若 M3 后做,共修仪式(v3-m4 T4.6)挪入本里程碑。

新模块:`config/bonds.py`、`services/bonds.py`、`handlers/bonds.py`(callback 前缀 `bond:`)。
**README §0.B-1**:原 spec §8.1 的 `config.social` 与现有群播报模块冲突,评审定名 `bonds`,
spec §8.1 已同步回改(2026-07-08)。

---

## 任务清单

### T3.1 关系表 schema(`models/db.py`)

按 spec §8.2 原样落 `social_bonds` + `bond_milestones` + 全部索引:

- `social_bonds`:kind(`mentor`/`partner`)、status 状态机
  `pending ─ 确认→active ─ 解除→dissolved / 拒绝→declined / 48h 超时→expired`;
  `active_days` + `last_active_day`(mentor 行,Asia/Shanghai 日界)。
- **partner 镜像双行的唯一索引在本期一并建好**(`idx_bonds_partner_a`),避免 M4 二次迁移;
  M3 只用 mentor 语义。
- 唯一索引兜底:`idx_bonds_mentor_b`(徒弟同一时间一位师父,pending 占位防并发双拜);
  师父 active 徒弟 ≤3 用 `BEGIN IMMEDIATE` 内 count 兜底(索引表达不了)。
- `bond_milestones` PK `(bond_kind, a_id, b_id, milestone)`:终身一次性发放去重。
- pending 48h 过期:结算任务置 `expired`(并入现有 1h 间隔 token 清理任务或独立 job)。
- **冷却语义(spec §5.5,服务层不得各自解释)**:冷却只挂 `dissolved`(7 天,查
  `dissolved_at + 7d`);`declined` / `expired` 不触发冷却。

**验收**:并发双拜被唯一索引拒绝;pending 超时置 expired;declined/expired 后可立即发起新关系;
dissolved 后 7 天冷却生效。

### T3.2 拜师 / 解除 / 重拜(`services/bonds.py`)

- 门槛:师父元婴期+;徒弟**筑基圆满及以下**(境界差硬门槛)。
- 流程:任一方发起,双向确认(一次性 token + `db.transaction()`);写入即生效。
- 解除:任一方单方解除 → `dissolved`,双方 7 天冷却;已发里程碑不回收,该 `(师父,徒弟)` 对
  后续里程碑不再计数(`bond_milestones` 终身去重天然兜底)。
- **重拜代价公示**:拜师与解除确认界面文案均明示"解除后重拜,出师累计活跃天数从 0 重计"。

### T3.3 传承收益:+5% 修炼效率 + 每日传功(`services/bonds.py` + `services/character.py`)

- 徒弟出师前修炼效率 +5%:接入 SECLUSION clamp(0.60)合算管线,不上调 clamp 总量;
  **截断透明化**:被 clamp 截断时收功文案含"已达闭关增益上限"(与 M4 双修共用同一处理)。
- 每日传功:师父发起,徒弟获小额修为(额度按徒弟境界配 `config/bonds.py`;师父无消耗;
  每对每日一次)。**徒弟当日有前台行为(闭关收功/历练/秘境/任务)才可领取**;
  额度 < 徒弟同时段正常闭关收益的 50%(加速不代练)。

### T3.4 活跃天数落库(`services/bonds.py`,挂接各前台行为结算点)

- 统一 helper `record_disciple_activity(conn, user_id, now)`:徒弟当日首个前台行为时,
  `last_active_day != 今日` 则 `active_days += 1` 并更新 `last_active_day`,同事务写入。
- 挂接点:闭关收功、历练结算、秘境结算、任务领奖(逐一列出调用点,漏一处则活跃统计偏低)。
- **传功"当日活跃"校验与本判定共用同一数据**(spec §4.5)。

**验收**:当日首个行为 +1、同日重复不重计;解除冻结计数;重拜归零。

### T3.5 里程碑奖励 + 出师 + 桃李称号

- 徒弟突破金丹/元婴:师父得道行 + 播报,每 `(师父,徒弟)` 每里程碑终身一次(`bond_milestones`)。
- **出师双条件**:徒弟达元婴初期 **且** `active_days ≥ 8`(门槛常量落 `config/bonds.py`,
  注释锚定"最高活跃档到元婴初期 ≈8 天",成长曲线调整时随之重算)。
- 出师双方一次性奖励:道行 + 绑定材料 + 称号进度;**全绑定,不含灵石与可交易物**。
- 桃李称号线:累计出师 1/3/5 名,递进称号 + `game_events` 播报。

### T3.6 师父周活跃回报(APScheduler 周任务)

- 每周结算(建议 cron 周日 23:40,错开 PvP 23:55 / 赛季 23:50 / 宗门战 23:45):
  按每名 active 徒弟本周活跃天数发道行,初版 **5 道行/活跃日、封顶 30/周/徒弟**(`config/bonds.py` 可调)。
- **计入道行周上限**(`_cap_overflow_daohang` 同一 weekly_activity 计量口径,不新增资源入口);
  出师后停发(仅 active 徒弟计数)。

**验收**:按活跃日计 / 每徒弟封顶 / 计入周上限 / 出师停发——各一条单测;
3 名满勤徒弟合计 90/周 ≪ 周上限 600,无套利空间断言。

### T3.7 七日引导任务链(`config/quests.py` 管线 + `config/bonds.py`)

- 注册起 7 天,每天 1~2 个教学任务(首次历练/炼丹/上架坊市/加入宗门…),复用现有
  `period/event/target/reward` 任务管线(README §0.A),按 `characters` 注册时间门控。
- 奖励:绑定丹药、灵石、精力;**全绑定、只对新注册角色开放、既有角色不可补领**。
- 师徒联动:徒弟完成引导任务时,师徒双方各得小额奖励(教学行为与奖励直接关联)。

### T3.8 handlers + 播报(`handlers/bonds.py`)

- `/master` 或并入现有社交入口(定稿时定命令名):拜师/收徒/传功/解除/出师界面;
  状态变更全部 `action_callback_data` + `consume_action_callback`;私聊 gate。
- 拜师成立/出师/桃李称号进 `game_events` 群播报。

---

## 验收测试清单(spec §9 师徒条目逐条映射)

- 境界差门槛生效(高境界互拜被拒)。
- 每对每里程碑终身一次,解除重拜不重发。
- 传功每日一次、额度受限、徒弟当日无活跃领取被拒。
- 出师元婴 + 活跃 ≥8 双条件;出师奖励全绑定(上架坊市/拍卖被拒)。
- DB 兜底:双拜被唯一索引拒;pending 48h 过期;declined/expired 不触发冷却;dissolved 7 天冷却。
- 活跃天数:首个行为 +1 / 同日去重 / 解除冻结 / 重拜归零 / 出师校验读该列。
- 周活跃回报四断言(T3.6)。
- +5% 传承进 SECLUSION clamp(回归 `test_buff_caps.py`);截断时文案含"已达闭关增益上限"。
- **SECLUSION clamp 占用切片**(spec §9):宗门/道途/飞升/据点/传承各来源典型档占用表;
  "普通配置档(宗门+单道途)"下传承有完整边际收益。
- 引导任务:仅新角色可领、奖励全绑定、师徒联动奖励发放。

## M3 完成定义(DoD)

1. `python -m pytest` 全绿,上述清单全部有测试。
2. 反滥用链路完整:境界差 + 双条件出师 + 终身去重 + 当日活跃校验 + 全绑定,各有单测。
3. 周事件总量审计:周活跃回报为**被动发放**(师父无操作),传功为每日可选;
   无新增周必做,审计表存档。

## 风险与回避

| 风险 | 回避 |
|---|---|
| 高境界小号互刷里程碑/传功 | 境界差硬门槛 + 元婴 & 8 活跃天 + 终身去重 + 额度 <50% 闭关收益 |
| 活跃天数挂接点遗漏导致出师卡死 | T3.4 列全调用点清单;测试覆盖每类前台行为各记一次 |
| 传承 +5% 与既有闭关 buff 叠加越顶 | 进 clamp + 占用切片测试;截断透明文案防误报 bug |
| 周回报 job 与其他周日 job 撞点 | 23:40 错峰;job 幂等(按周 key 去重发放) |
