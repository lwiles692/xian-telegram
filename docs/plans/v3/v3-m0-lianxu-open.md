# V3-M0 炼虚开放:v2 收口 + 炼虚配置 + 突破链 + 三图

> 对应 spec-v3 §1.1、§3.1~§3.5、§3.8、§10。
> 目标:化神圆满玩家获得炼虚突破与炼虚地图目标;溢出分流上移 + 降档宽限期;埋 M1 线索。
> 前置:无。**T0.1 / T0.2 两个 v2 收口项最先做**,后续所有炼虚门槛都在含它们的档位下验收。

---

## 任务清单

### T0.1 v2 收口:issue #45 元婴及以上常规道行来源

按 issue #45 验收标准 + spec-v2 §4.3:

- 元婴期及以上的**历练结算**给少量道行,写 `path_events`。
- 元婴期及以上的**秘境结算**给少量道行,写 `path_events`。
- 世界 Boss 挑战/击杀奖励明确道行口径。
- 炼制、宗门任务、PvP 周榜:按 spec 给少量道行,或明确延后并同步更新 spec-v2。
- 额度经 balance_sim 校验不绕过道行周上限 / 活动上限。

**验收**:新增测试覆盖 ≥2 条常规来源 + 1 条"非元婴玩家不获得道行"边界;`test_economy` 道行产出回归。

### T0.2 v2 收口:化神圆满满 buff 档进 balance_sim(`tools/balance_sim.py`)

- 新增 `HUASHEN_FULL_BUFF_ATK` / `HUASHEN_FULL_BUFF_SURV` 两档(spec §3.2:攻击极端≈剑修圆满、
  生存极端≈体修圆满):化神现役装备(`HUASHEN_GEARED`/`HUASHEN_BRANCH_GEARED` 基础)+
  `dao_path` 单条拉满 + `dao_refine=REFINE_MAX_LEVEL` + 飞升被动满级 + `extra_pct` 推至 clamp 上限
  (做法沿用 `YUANYING_FULL_BUFF`,`tools/balance_sim.py:41`)。
- 若 profile 管线尚不支持飞升被动项,先补管线(与 `dao_refine` 同样的键值注入方式)。

**验收**:`python -m tools.balance_sim` 报告含两档输出;后续 T0.11 所有炼虚门槛断言基于这两档。

### T0.3 炼虚配置六件套(`config/realms.py` + `config/shop.py`)

按 spec §3.1(全部初版可调):

```
REALM_NAMES += ["炼虚期"];  REALM_STAGES[5] = _SUB_STAGES
STAMINA_CAP[5] = 280;      SECLUSION_STAGE_HOURS[5] = 720
_REALM_BASE_COST[5] = 4_000_000(_STAGE_MULT 沿用 1.20)
_ANCHORS[5] = (初期 hp78000/mp6300/atk5600/df4100/spd1300/crit420,
               圆满 hp170000/mp13500/atk12000/df8800/spd2300/crit700)
BIG_BREAKTHROUGH[5] = {"pill": "炼虚丹", "base_rate": 0.45, "tribulation": True}
config/shop.py: STAMINA_BUY_BASE[5] = 6000
```

- 模块 docstring"大境界索引 0..4"同步改 0..5;AGENTS.md 的 realm 索引说明同步。
- grep 全仓 `range(4)` / `range(5)` / 境界档硬编码,同步为 `len(REALM_NAMES)` 或补档
  (README §0.C 触点清单)。

**验收**:spec §9 第 1 条——五个配置 dict 都含 realm 5 的存在性测试;`/me`、历练、商店买精力在
化神号上无 KeyError(现有 handler 测试回归)。

### T0.4 炼虚丹 + 残方管线(`config/items.py`、`config/recipes.py`、掉落表)

- `config/items.py`:新增 `炼虚丹`、`炼虚丹残方`、`炼虚丹方`(recipe 物品);
  `NO_TRADE += {"炼虚丹"}`(坊市/拍卖行共用,spec §3.4)。
- `config/recipes.py`:炼丹配方 `lianxu_pill`(需习得丹方);**残方合成保底**:`炼虚丹残方 ×4 →
  炼虚丹(产物 bound=1)`,复用 `huashen_pill` recipe 管线(`config/recipes.py:107`)。
  材料配比按 spec §3.4 的 `×4`,非照抄化神丹的 `残方×6+妖丹×4`,避免实施时误配。
- 掉落来源(spec §3.4 首破权重原则:第一枚 100% 落在化神可及内容):
  - 化神难图 `天外古墟`:极低概率 `炼虚丹残方` / `炼虚丹`;
  - 秘境 `太虚天门` 深层:完整丹方 / 材料 / 残方(稳定小概率);
  - 化神世界 Boss 前列奖励:掉材料,参与奖不掉完整丹;
  - 炼虚易图:低概率丹材,仅作已突破玩家的补充,不得是任何丹材唯一来源。
- NPC 商店不直售。

**验收**:残方 ×4 合成可用、产物绑定且不可绕过绑定语义;炼虚丹上架坊市被拒;
balance_sim 首破路径校验见 T0.11。

### T0.5 失败累计保底(`models/db.py` + `services/breakthrough.py`)

- `characters += big_fail_streak INTEGER NOT NULL DEFAULT 0`(`_ensure_column`)。
- 调用点改造(`services/breakthrough.py:139` 附近):`char["realm"]==4`(化神→炼虚)时
  `rate = big_success_rate(...) + big_fail_streak * 0.10`,总率仍 ≤0.95;
  失败(含渡劫失败)`big_fail_streak += 1`,成功清零。**低境界大突破不读不写**
  (spec §8.2 字段边界注释原样写进代码)。

**验收**:失败递增/成功清零/总率 ≤95% 各一条单测;低境界突破不受影响的边界测试;
突破成功率文案展示当前保底加成(玩家可感知)。

### T0.6 虚空劫(`config/events.py` + `services/breakthrough.py`)

- 仿神魂劫分流先例(`services/breakthrough.py:84`):`_tribulation_actions` 增加
  `target_realm==5 → XUKONG_TRIBULATION_ACTIONS`;选项初版沿用纯防御/回复三选
  (凝守本源 / 祭护体法宝 / 服大还丹),文案换虚空/肉身崩解主题。
- 劫名分支(`services/breakthrough.py:210` `trial_name`)加"虚空劫"。
- "直面心魔"选项**不在 M0 做**,是 M1 T1.6(spec §3.3)。

**验收**:化神圆满 + 炼虚丹 + 修为达标可发起突破并进入虚空劫;缺丹返回 `need_pill`;
失败损失当前修为 30%、不跌境(spec §9 第 2 条)。

### T0.7 炼虚三图(`config/maps.py` + `tools/balance_sim.py`)

按 spec §3.5:

| 地图 | 难度 | 精力 | 时长 | 独占掉落 |
|---|---|---:|---|---|
| 太初雾泽 | 易 | 20 | 15~18 分钟 | 雾泽虚砂 |
| 虚空裂海 | 中 | 24 | 18~22 分钟 | 裂海空髓 |
| 混沌古狱 | 难 | 28 | 22~26 分钟 | 混沌残核 / 炼虚丹材料 |

- 低阶折叠/扫荡沿用现有模型;`CONTENT_REALM` 加三张图(`tools/balance_sim.py:56`)。
- 独占材料先落物品表(炼虚装备/丹药消耗在 M1 接上;道途宗师/飞升材料按 spec §3.8)。

**验收**:见 T0.11 门槛与经济断言。

### T0.8 溢出分流上移 + 降档宽限期(`models/db.py` + `services/settle.py` + `services/character.py`)

- `overflow_split` 判据 len-based,追加 realm 5 后炼虚圆满自动走顶点档(8% 道行 +
  每十万溢出修为凝 1 飞升点)、化神圆满自动落次顶点档(3%/0)。道行周上限 600，
  飞升点溢出来源周上限 14(spec §3.8)。
- 新增 `game_flags(key TEXT PRIMARY KEY, value TEXT NOT NULL)` 表(SCHEMA + `init_db`)。
- **宽限期**:`init_db` 内可重入迁移——`game_flags` 无 `overflow_demote_grace_until` 时写入
  `部署时刻 + 28 天`(已存在则不覆盖,幂等)。
- `overflow_split` 增加宽限判定入口(纯函数保持可测:宽限截止时间戳作参数传入,由调用方
  `services/character.py` 从 `game_flags` 读取并缓存):宽限期内化神圆满按顶点档分流。
- 面板/收功界面展示玩家当前分流档位(顶点档 / 次顶点档 / 宽限中)。

**验收**(spec §9):炼虚圆满按十万修为凝点;化神圆满宽限内顶点档、期满次顶点档
(单测卡宽限截止两侧时间点);道行周上限 600、凝点周上限 14 跨档生效;
`game_flags` 迁移重复执行不覆盖已有值。

### T0.9 公告三处文案(M0 上线**前置验收**,spec §3.8)

- 版本公告、`/help`(`handlers/help.py`)、收功文案三处明示:宽限截止日期、降档后档位
  (3% 道行 / 0 飞升点)、突破炼虚可恢复完整分流。
- **缺任一处,M0 不得上线**(测试断言三处文案含关键字)。

### T0.10 M1 线索埋点(spec §3.4 末)

- 化神难图 / 太虚天门低概率掉 `炼虚装备图纸残页`(物品先落表,M1 才有消费语义)。
- 炼制界面(`handlers/craft.py`)展示"待解锁"的炼虚装备/丹方条目(灰色占位文案)。

### T0.11 数值定稿(贯穿 T0.3~T0.8,balance_sim 迭代反推)

M0 验收 profile:**炼虚初期锚点 + 现役化神装备/功法**(spec §1 约束:不许拿裸锚点调参);
上界档:T0.2 的化神满 buff 两档。全部按"可刷 / 门槛"口径:

- 化神满 buff 档可刷炼虚易图小怪(允许磨);**过渡档**:可低效磨中图普通小怪
  (单位精力收益显著差于易图但 >0)。
- 炼虚中/难图 Boss 与多遭遇连战压住化神满 buff 档:挑战成功率 **<5%**。
- 炼虚初期(+化神装备)刷易图稳定、中图小怪可刷;中图 Boss / 难图分别是中期 / 后期门槛。
- 炼虚圆满碾压化神内容,但化神内容收益非最佳成长路线(修为收益曲线:炼虚图 > 化神图)。
- **推进时长**:普通活跃档(根骨 60、有效闭关 18h/日)炼虚初期→圆满 **6~9 周**;高活跃 ≥4 周。
  超区间联动调 `SECLUSION_STAGE_HOURS[5]` 与炼虚地图修为;最终定稿为 720,覆盖 T0.3 初案 144。
- **首破周期**:化神圆满正常日程(每日太虚 ×2 + Boss + 难图)首枚炼虚丹期望 **2~4 周**,
  期望来源 100% 化神可及内容;45% + 保底下期望"进炼虚"**4~6 周**。超出调掉率或保底参数。
- **经济**:炼虚图灵石/精力 < 300×75%;分两档回归——存量化神档(余粮 + 280 精力上限)与
  新进化神档(现刷现出)的灵石流水、精力负担各在目标区间(spec §9)。

**验收**:`tests/test_balance.py` + `tests/test_economy.py` 上述断言全绿;
`python -m tools.balance_sim` 报告数值落区间。

---

## M0 完成定义(DoD)

1. `python -m pytest` 全绿(304 存量 + M0 新增)。
2. `python -m tools.balance_sim`:炼虚三图门槛/首破路径/推进时长/经济两档全部落区间,套利全堵。
3. T0.9 三处公告文案齐备(前置验收)。
4. schema 改动全部幂等(`_ensure_column` / 可重入 `game_flags` 迁移),旧档无损。
5. 周事件总量审计:M0 无新增周必做事件(炼虚图/突破为存量行为升级),出具审计表存档。

## 风险与回避

| 风险 | 回避 |
|---|---|
| M1 炼虚装备上线后回溯打穿 M0 门槛 | M0 门槛基于"化神装备"档预留头寸;M1 落 LIANXU_GEARED 后**回归重调全部炼虚门槛**(跨里程碑依赖,见 v3-m1) |
| 首破死锁("先有鸡还是先有丹") | 首破权重原则进 balance_sim 断言:期望路径 100% 化神可及;残方 ×4 提供确定性进度条 |
| 宽限期写死代码导致部署日错位 | 截止时间只存 `game_flags`,迁移幂等不覆盖;单测用注入时间戳,不依赖部署时刻 |
| 保底字段将来被低境界误用 | 字段边界注释 + "低境界不读不写"单测双保险(spec §8.2) |
