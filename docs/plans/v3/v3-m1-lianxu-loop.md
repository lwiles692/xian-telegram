# V3-M1 炼虚完整链路 + 心魔劫

> 对应 spec-v3 §3.6、§3.7、§3.2 装备验收口径、§7.1、§10。
> 目标:炼虚期完整 PvE(秘境 + 世界 Boss)与装备炼制链;金丹起所有天劫获得"直面心魔"选项。
> 前置:M0 已上线。**M1 落 LIANXU_GEARED 档后必须回归重调 M0 全部炼虚门槛**。

---

## 任务清单

### T1.1 炼虚秘境 虚空神殿(`config/dungeons.py`)

新增 key `xukong`,按 spec §3.6:

| 字段 | 取值 |
|---|---|
| name / realm | 虚空神殿 / 5 |
| layers | 6 |
| stamina | 70 |
| entry_stone | 4000 |
| 每日次数 | 2(走现有 `dungeon_runs` 日限) |
| drops | 炼虚丹材料、炼虚法宝、道途/飞升材料、拍卖行白名单材料 |

- 怪物数值由 T1.5 实跑反推;太虚天门保持在役(自然降级为次级日常,不做废弃)。

**验收**:炼虚初期(LIANXU_GEARED)推进 **40%~70%** 层数;炼虚圆满稳定通关;
入场费 + 每日 2 次净收支不形成套利(净灵石/精力 < 炼虚首买 300 的 75%);
日常精力自洽:70×2=140 ≤ 280,留出 Boss(20)+ 历练。

### T1.2 炼虚世界 Boss 档(`config/bosses.py`)

- `WORLD_BOSSES["lianxu"] = {name:"吞虚魔蟒", realm:5, duration:2*3600, stamina:20, …}`。
- **`_REALM_TIER[5] = "lianxu"`**(`config/bosses.py:58`,spec §3.7 未列,README §0.C)。
- `total_hp` 沿用"chip 伤害反推"口径:目标击杀 20~80 次区间;同群独立 + 按 `cultivator_count` 缩放,
  逻辑零改动仅加档。
- drops:炼虚材料、道途材料、飞升点材料;前列奖励掉炼虚丹材料(补 M0 来源),参与奖不掉完整丹。

**验收**:`world_boss_kill_challenges("lianxu", 5, 后期)` 落 20~80;`boss_key_for_realm(5)=="lianxu"`;
小群缩放断言覆盖 lianxu 档。

### T1.3 炼虚装备 / 材料 / 炼制链(`config/items.py`、`config/equipment.py`、`config/recipes.py`)

- 新增炼虚法宝/防具/饰品(平加 + 少量词条),来源:虚空神殿、炼虚 Boss、混沌古狱。
- 消费 M0 埋点:`炼虚装备图纸残页` 合成图纸;炼制界面"待解锁"条目转正。
- 三图独占材料(雾泽虚砂/裂海空髓/混沌残核)接入配方;强化/重铸沿用现有管线,无新机制。
- 白名单高阶材料(混沌残核等)在坊市可交易(M2 拍卖行上线前的过渡,spec §6.1)。

**验收**:炼虚圆满 + 炼虚装备属性接近 `_ANCHORS[5]` 圆满 + 装备合理区间,不越 clamp 预留头寸。

### T1.4 LIANXU_GEARED 档 + 门槛回归重调(`tools/balance_sim.py`)

- 新增 `LIANXU_GEARED`(炼虚装备 + 功法)profile。
- M0 用"化神装备近似"调的炼虚门槛,按 LIANXU_GEARED **回归重调**:初期 GEARED 稳刷易图、
  推进中图;圆满 GEARED 通难图。
- 保留 M0 的化神满 buff 上界断言(仍 <5% 过炼虚中/难 Boss)与过渡档断言(可低效磨中图小怪)。

**验收**:炼虚三图 + 虚空神殿 + 炼虚 Boss 断言全部基于 LIANXU_GEARED 重新固定。

### T1.5 炼虚内容数值定稿(贯穿 T1.1~T1.4)

- balance_sim 迭代反推怪物/掉落数值至 T1.1/T1.2/T1.4 全过。
- 白名单材料产出进反套利校验(为 M2 拍卖行做前置:材料可拍不得打穿"买精力→刷钱"红线)。

### T1.6 心魔劫选项(`config/events.py` + `services/breakthrough.py` + `models/db.py`)

spec §7.1,金丹起**所有**交互式天劫(天劫/神魂劫/虚空劫)第三段新增可选项:

- `tribulation_sessions += reward_flag TEXT`(`_ensure_column`,幂等)。
- 选项 `直面心魔`:本段**无任何减伤**;选择即置 `reward_flag`。
- 结算分支:渡劫成功且 `reward_flag` 置位 → 发 `道心通明` 临时 buff(24h 闭关效率 +10%,
  **计入 SECLUSION clamp**)+ 少量道行;渡劫失败 → 常规惩罚外**额外损失 5% 当前修为**。
- 参数常量落 `config/events.py` 天劫配置旁(README §0.B-5:不新建 config/tribulation 文件)。
- 成功/失败均 `game_events` 播报。

**验收**(spec §9):选"直面心魔"本段无减伤;成功发道心通明(24h/+10%/进 clamp,
回归 `test_buff_caps.py`)+ 道行;失败额外扣 5% 修为;`reward_flag` 迁移幂等;
三种天劫(金丹/元婴→神魂/化神→虚空)均出现该选项。

---

## M1 完成定义(DoD)

1. `python -m pytest` 全绿;炼虚门槛/秘境/Boss/装备测试基于 LIANXU_GEARED 齐备。
2. `python -m tools.balance_sim`:炼虚全内容数值落区间,套利全堵(含白名单材料)。
3. 炼虚日常闭环成立:三图历练 + 虚空神殿 ×2 + 炼虚 Boss,精力 280 分配自洽。
4. schema 仅 `_ensure_column` 加列(`reward_flag`)。
5. 周事件总量审计:虚空神殿/炼虚 Boss 为存量日常的境界平移,非新增周必做;审计表存档。

## 风险与回避

| 风险 | 回避 |
|---|---|
| 炼虚装备上线回溯打穿 M0 门槛 | T1.4 全量回归重调,并保留化神满 buff 上界护栏断言 |
| 心魔劫 +10% 闭关 buff 与宗门/道途/飞升/据点叠加越顶 | 进 SECLUSION clamp;`test_buff_caps.py` 全量回归(v2 B-3 教训) |
| 虚空神殿掉落 + 白名单材料形成套利 | 净收支 + 材料售价一起进 balance_sim / test_economy |
| total_hp 与假人尺度错配 | 沿用 chip 伤害反推口径,勿手填 |
