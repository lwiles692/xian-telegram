# V3-M5 本命法宝雏形(骨架)

> 对应 spec-v3 §7.2、§8.2、§10。
> 目标:与境界正交的长期成长维度,承接炼虚材料 sink,与器修道途协同。
> 前置:M1(炼虚材料管线)、M2(拍卖托管语义,认主实例需排除)。
> **spec 明确:M5 启动前补 detail 文件**——本文件只固化骨架与红线,数值与喂养曲线届时定稿。

新模块:`config/natal.py`、`services/natal.py`(handler 并入 `handlers/bag.py` 或独立,届时定)。

---

## 任务骨架

### T5.1 schema(`models/db.py`,均 `_ensure_column` 幂等)

- `characters += natal_instance_id INTEGER`
- `item_instances += natal_level INTEGER NOT NULL DEFAULT 0`(认主后才 >0)

### T5.2 认主 / 解缚(`services/natal.py`)

- 认主:元婴期起;对象为金丹品阶及以上、未上拍(`status='normal'`)的法宝实例;
  仪式消耗材料 + 灵石;认主后实例**永久绑定**(`bound=1`):不可交易、不可上拍、不可分解。
- 解缚("斩缚"):高额灵石,本命等级清零;成本高于常规装备更换成本(数值 detail 定稿)。
- 一次性 token + 事务;认主/解缚播报。

### T5.3 喂养成长

- 喂养材料/器魂提升本命等级,初版上限 **10 级**;每级小幅提升该法宝主属性。
- 加成**计入 ATTACK/SURVIVAL clamp(0.25)**,走全局属性合算管线,不旁路。
- 喂养成本曲线 `config/natal.py`(detail 定稿);消耗以炼虚图/秘境材料为主(材料 sink 定位)。

### T5.4 器修协同

- 器修道途提升喂养效率 / 降低成本,作为器修专属长期材料 sink(与 `config/dao_paths.py` 接口对齐)。

### T5.5 交易隔离

- 认主实例排除在拍卖托管之外:绑定语义优先,M2 的实例读取入口统一过滤天然兜住
  (`bound=1` 不可拍);再补 `natal_instance_id` 指向实例不可分解/赠送的显式校验。

---

## 验收红线(spec §7.2)

- 本命加成进 clamp 回归(`test_buff_caps.py` 全量)。
- 认主实例不可进任何交易路径(坊市/拍卖/赠送/分解各一条被拒测试)。
- 喂养材料消耗进 balance_sim:作为新材料 sink 反向支撑炼虚图/秘境长期刷图价值,
  且不与既有 sink(道途淬炼)互相挤兑(参考 v2 道途淬炼 sink 的限流经验)。
- 解缚清零等级、费用高于常规换装成本。

## M5 完成定义(DoD)

1. detail 文件(数值/曲线/费用)先行评审通过,再动工。
2. `python -m pytest` 全绿;验收红线全部有测试。
3. 周事件总量审计:喂养为可选长线行为,无周必做新增。
