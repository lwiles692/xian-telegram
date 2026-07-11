# M2 拍卖行周事件总量审计

> 对应 `v3-m2-auction.md` DoD #4。结论：拍卖行是可选交易系统，不新增周必做；群播报仅为低频曝光，不要求玩家定时上线。

| 事项 | 是否新增周必做 | 玩家动作 | 频次上限 | 审计结论 |
|---|---|---|---|---|
| 挂拍法宝/材料 | 否 | 有交易需求时自选挂拍 | 每人同时在拍 3 件 | 可错过，无成长损失；挂拍费与成交税为灵石销毁 |
| 出价 / buyout | 否 | 有购买需求时自选出价 | 无周期任务奖励 | 可错过，无日/周奖励绑定 |
| 新拍上新群播 | 否 | 无需响应 | 每已知群每小时最多 1 条汇总 | 只播新上拍汇总，静默窗口推进，避免刷屏 |
| 结拍前 1 小时群播 | 否 | 无需响应 | 每场拍卖每群最多 1 次 | `auction_closing_broadcasts` 去重，不形成定时任务压力 |
| 关注拍卖私聊 | 否 | 玩家主动关注后接收提醒 | 被超价、临近结拍各按事件触发 | 私聊仅提醒关注者，可随时取消关注 |
| 天价成交群播 | 否 | 无需响应 | `auction.high_price_sale` 每人每日限 2 条 | 仅记录罕见成交，不附带收益 |

## T2.8 审计入口

- 服务层：`services.auction.audit_report()` 汇总高价拍卖与高频互拍。
- 离线巡检：`python -m tools.auction_audit --db data/xian.db` 输出 JSON 审计报告。
- 反套利：白名单材料继续复用 `tools.balance_sim` 的可交易估值档口，`tests/test_balance.py::test_auction_whitelist_material_values_stay_under_buy_margin` 固定红线。
