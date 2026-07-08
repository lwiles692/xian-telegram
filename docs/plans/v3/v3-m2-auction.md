# V3-M2 拍卖行:法宝实例与高阶材料的价格发现

> 对应 spec-v3 §6、§8.2、§10。
> 目标:英式拍卖 + buyout、escrow 实扣、防狙击、实例托管、幂等结算、审计与曝光。
> 前置:M1(白名单材料已产出并在坊市过渡)。**独立开发独立验收**,不与其他系统混做。

新模块:`config/auction.py`、`services/auction.py`、`handlers/auction.py`(callback 前缀 `auc:`,
`bot/app.py` `_COMMANDS` 加 `/auction 拍卖行` + `dp.include_router`)。

---

## 任务清单

### T2.1 schema(`models/db.py`)

按 spec §8.2 原样落表 + 索引:

- `auctions`(status 状态机 `active → sold/passed/cancelled`,单向)。
- `auction_bids`(全量出价流水)。
- `auction_escrow`(PK `(auction_id, bidder_id)`)。
- 索引:`idx_auctions_status_end`(结拍扫描)、`idx_auctions_seller`(挂拍上限)、
  `idx_auction_bids_auction`。
- `item_instances += status TEXT NOT NULL DEFAULT 'normal'`(`_ensure_column`)。

**验收**:建表/加列幂等,重复 `init_db` 无损。

### T2.2 配置(`config/auction.py`)

| 参数 | 初版取值 |
|---|---|
| 拍期 | 24h |
| 加价幅度 | ≥ 当前价 5% |
| 防狙击 | 结拍前 5 分钟出价顺延 5 分钟,最多 6 次 |
| 挂拍费 | 起拍价 1%,不退 |
| 成交税 | 10%(与坊市税率独立配置) |
| 同时挂拍上限 | 每人 3 件 |
| buyout 最低倍率 | 起拍价 ×1.2 |
| 系统底价 | 按品阶配置 |
| 白名单材料 | 天外残玉、混沌残核等,名单配置化 |
| 天价播报阈值 | 配置化 |

### T2.3 挂拍与托管(`services/auction.py`)

- **可拍校验**:法宝实例(未装备 `equipped_slot IS NULL`、`bound=0`、`status='normal'`、
  非本命 natal——M5 语义,先按 bound 兜住);白名单材料;禁拍 = `bound=1` ∪ `NO_TRADE`
  (炼虚丹/化神丹/转修令/保命符)。
- 实例上拍:同事务校验 + 置 `status='auction'`;材料上拍:上架即扣库存(坊市模型)。
- 挂拍费实扣(净 sink);同时挂拍 ≤3(`BEGIN IMMEDIATE` 内 count 后插入)。
- 撤拍:仅无人出价时可撤,挂拍费不退,实例/材料退回。

### T2.4 实例锁定统一过滤(`services/equipment.py` 等)

- `status='auction'` 的实例在**装备、强化、重铸、分解、赠送、再次上拍**全部路径排除——
  **在实例读取入口统一过滤**(spec §6.3:不允许各调用点自行判断);盘点现有实例读取函数,
  收敛到单一入口后加过滤参数。

**验收**:六条路径各一条"被拒"单测。

### T2.5 出价与 buyout(`services/auction.py`)

- 出价**实扣**:同一 `db.transaction()` 内 `characters.spirit_stone` 扣款 → 写 `auction_escrow`;
  前最高价者 escrow 原子退回;加价 ≥5%;写 `auction_bids`。
- 防狙击:结拍前 5 分钟内出价 → `end_at += 5min`、`extend_count += 1`(≤6)。
- **buyout**:卖家可选,须 ≥ 起拍价 ×1.2;出价 ≥ buyout 按 buyout 价立即成交(多余不收),
  同一事务:扣买家、退前最高价者 escrow、过户/交货、卖家收款(扣税 10%)、置 `sold`——
  **不进防狙击顺延**;照常落 bids 与事件日志,天价阈值照常适用。
- 全部状态变更走一次性 `callback_tokens` 确认。

### T2.6 结算任务(`bot/app.py` + `services/auction.py`)

- APScheduler interval 任务(每 1 分钟,与现有 `notify_ready_actions` 同频)扫
  `idx_auctions_status_end` 到期拍卖。
- **结算幂等**:状态机单向,`UPDATE … WHERE status='active'` 抢占,重复触发 no-op。
- 成交:过户/交货 + escrow 转卖家(扣税)+ 恢复实例 `status='normal'`(归属新主)+ 播报;
  流拍:退货退款 + 恢复 `status='normal'`,置 `passed`。
- 全流程 `db.transaction()`;并发出价靠 `BEGIN IMMEDIATE` 串行化,不超卖不双花。

### T2.7 曝光与通知(`services/auction.py` + `handlers/auction.py`)

spec §6.5 低流动性群处理:

- 新拍上架、**结拍前 1 小时**各推一次群播报(仿 `market_service.notify_recent_listings` 的
  hourly 任务模式,或并入 T2.6 扫描任务)。
- 玩家可"关注"拍卖:被超价 / 临近结拍收私聊(复用现有通知任务管线)。
- 跨群橱窗不做,但拍卖数据**不做群内隔离假设**(留四期接口余地)。

### T2.8 审计与反套利

- 复用坊市审计口径:异常价、高频对倒(同两账号反复互拍)出审计日志。
- 天价成交进 `game_events` 群播报。
- 白名单材料进 balance_sim 反套利校验(T1.5 已建的档口回归)。

---

## 验收测试清单(spec §9 拍卖行条目逐条映射)

- 绑定物 / `NO_TRADE` 名单 / 已装备实例不可上拍。
- `status='auction'` 实例六条操作路径全部被拒(T2.4)。
- 出价实扣入 escrow、被超价原子退回;并发出价不超卖(两连出价串行断言)。
- 防狙击顺延最多 6 次;第 7 次不再顺延。
- **结拍幂等**:重复触发结算 no-op。
- 流拍退货退款;成交过户 + 扣税正确 + 实例恢复 `normal`;挂拍费净 sink(系统灵石总量断言)。
- buyout:×1.2 校验;满 buyout 立即成交不顺延;前最高价者 escrow 退回;
  出价 ≥ buyout 按 buyout 成交不多收;落 bids 与事件日志。
- 拍卖行只转移灵石不产生灵石(全流程灵石守恒 - 税 - 挂拍费断言)。

## M2 完成定义(DoD)

1. `python -m pytest` 全绿,上述验收清单全部有对应测试。
2. balance_sim:白名单材料可拍不打穿"买精力→刷钱"红线。
3. 结算任务在 bot 重启后可恢复(到期未结拍卖被下一轮扫描结算)。
4. 周事件总量审计:拍卖为可选行为、无周必做新增;通知频次(新拍/结拍前 1h)不构成刷屏,审计表存档。

## 风险与回避

| 风险 | 回避 |
|---|---|
| 并发出价双花 / 超卖 | escrow 实扣 + `BEGIN IMMEDIATE` 串行 + 并发单测 |
| 结算任务重复触发重复发钱 | 状态机单向 + `WHERE status='active'` 抢占更新 + 幂等单测 |
| 实例锁定漏一条路径(如新功能忘过滤) | 读取入口统一过滤;M5 本命、后续新实例操作一律走该入口 |
| 小群流动性差、拍卖沦为摆设 | T2.7 曝光双推 + 关注通知;上线后观察成交率再评估跨群橱窗 |
| 白名单材料价格倒挂坊市 | 双渠道并存期监控;审计脚本比对坊市/拍卖成交价 |
