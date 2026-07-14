# Telegram 富文本展示优化设计

## 目标

为当前 Telegram 文字 RPG 建立统一、安全的消息展示层，并按信息密度优化大段平铺文案。短反馈保持克制，交互面板使用 Telegram 普通消息实体，帮助、公告和战报等报告型内容使用 Bot API 10.1 Rich Messages。

本次只改变消息的结构、样式和发送方式，不修改游戏数值、业务状态、按钮行为、回调协议、一次性令牌、数据库结构或调度任务。所有新增文案、注释和文档继续使用中文，并保持现有修仙口吻。

## 方案选择

采用“分层混合并提供回退”的方案：

- 一句话状态、错误和确认结果继续使用纯文本；
- 角色面板、商店、悬赏等交互页面使用 aiogram 格式实体；
- 帮助、版本公告和战斗结算使用 Rich Messages，同时携带语义一致的实体回退版本。

不采用全局 `parse_mode`。当前文案包含大量 MarkdownV2 保留字符，玩家名、宗门名等动态值也可能包含格式字符；全局解析会增加整条消息发送失败和格式注入风险。

Rich Messages 使用 Rich HTML，而不使用 Rich Markdown。动态文本统一经过 HTML 转义，静态标签由展示辅助函数集中生成，比在所有 handler 中维护 MarkdownV2 转义更稳定。

## 依赖与边界

将 aiogram 最低版本提升至 `3.29`，依赖范围为 `aiogram>=3.29,<4`，以获得 Bot API 10.1 的 `InputRichMessage`、`sendRichMessage` 和 `editMessageText.rich_message` 支持。

保持现有 Python 3、aiogram Router、polling、SQLite、APScheduler 和单进程架构。服务层继续返回业务 `dict` 和既有 `status` 词汇，不感知标题、粗体、HTML 或折叠区域。消息样式由 handler 或展示辅助模块负责。

通用内容类型、发送入口、HTML 转义和回退判断集中在新模块 `bot/presentation.py`。页面特有的中文结构仍留在对应 handler，避免形成收纳全站文案的巨型公共模块。服务层的主动通知可以调用 `bot.presentation.send()`，但不得依赖任何 handler。

## 消息内容模型

展示入口接受三类内容：

- `str`：纯文本短反馈；
- aiogram `Text`：由 `Text`、`Bold`、`Italic`、`BlockQuote`、`ExpandableBlockQuote` 等节点构造的普通消息；
- `RichPage`：包含 Rich HTML、实体回退内容和页面标识的报告型内容。

`RichPage` 的页面标识仅用于日志分类，例如 `help`、`explore_result` 或 `pvp_result`。日志不得保存玩家名、宗门名或完整战斗正文。

新增统一展示入口，概念接口为：

```python
MessageContent = str | Text | RichPage

await answer(message, content, markup)
await show(callback, content, markup)
await send(bot, chat_id, content, markup)
```

- `answer()` 发送 handler 对当前消息的回复；
- `show()` 编辑 callback 所在消息，无法编辑时补发；
- `send()` 服务于通知和 Boss 播报等主动发送场景。

这些入口负责将 `Text` 转换为 `text + entities + parse_mode=None`，或将 `RichPage` 转换为 `InputRichMessage`。handler 不直接拼发送参数，也不手写包含动态值的 HTML。

## 数据流

消息展示保持单向数据流：

```text
service 返回业务 dict
        ↓
handler/render_* 生成 MessageContent + InlineKeyboardMarkup
        ↓
answer / show / send 选择普通实体或 Rich Message
        ↓
Telegram 发送或编辑消息
```

业务数据只生成一次。Rich HTML 和实体回退版本从同一份结构化展示数据构造，不各自重新查询服务，也不形成两套业务判断。

## 页面分级

### 报告型长文

以下页面使用 `RichPage`：

- `/help`；
- 版本公告；
- 历练结算；
- 秘境结算；
- PvP 结算。

帮助页按“修行养成、历练斗法、经营交易、宗门社交”分组，保留全部现有命令并让命令继续可识别、可点击。

战报始终展开胜负摘要、收益、当前气血法力和剩余精力。逐回合日志放入 Rich HTML 的 `<details>`；实体回退版使用 `ExpandableBlockQuote`。沿用当前日志截断上限，不在本次增加消息拆分或分页。

### 交互型面板

以下页面使用 aiogram `Text` 实体：

- `/me`、背包、功法和法宝；
- NPC 商店、坊市和拍卖；
- 悬赏、师徒、道侣和宗门；
- 道途、飞升、周活动和宗门战；
- 世界 Boss 状态与排行等共享群消息。

`/me` 分为“境界与资源、法身六维、法宝功法、关系与状态”。坊市和拍卖条目按“编号与物品、数量与价格、剩余时间或状态”的固定顺序展示。悬赏按日常、周常和引导分组。师徒、道侣和宗门把本人状态、成员列表、待确认事项和用法说明分区。飞升和周活动把当前资源及本周状态放在规则和兑换列表之前。

### 即时反馈

操作成功、资源不足、冷却中、令牌过期和其他一句话结果继续使用纯文本。只有确有层级的信息才使用格式，避免每条消息都变成视觉卡片。

## 文案结构规范

所有迁移页面遵循以下规则：

1. 首行使用粗体页面标题；
2. 核心状态紧跟标题，玩家无需先读规则才能找到余额、境界或进度；
3. 使用真正的小节标题，移除 `—— 门人 ——` 一类字符分隔线；
4. 列表每行只表达一个对象，编号、物品名或角色名作为视觉锚点；
5. 规则说明使用斜体或引用，与实时状态区分；
6. 操作提示放在末尾，已有按钮能表达的动作不重复成长句；
7. 每个小节最多使用一个功能性 emoji；
8. 动态玩家名、宗门名和其他外部输入始终作为纯文本实体节点或经 `html.escape()` 处理。

## 编辑与回退

`show()` 采用以下顺序：

1. 优先编辑 callback 当前消息，并保留原有 inline keyboard；
2. Rich Message 编辑成功后结束；
3. Telegram 明确返回 Rich 格式解析失败或 Rich 能力不支持时，使用实体回退版本重试同一次编辑；这类错误由 `bot.presentation` 内部的窄范围判断函数识别，并以测试中列明的 Telegram 错误文本为准，不把所有 `TelegramBadRequest` 视为可回退错误；
4. 原消息不可编辑时补发新消息；补发 Rich Message 失败时再补发实体版本；
5. `message is not modified` 静默结束；
6. 未知 `TelegramBadRequest`、限流和网络异常不降级、不吞掉并继续抛出，避免重复消息掩盖真正故障。

普通消息和 Rich Message 互相切换时，按钮文字和 callback 数据保持完全一致。所有状态变更按钮继续使用 `action_callback_data()` 和 `consume_action_callback()`。

## 运行期开关与日志

新增环境开关：

```env
RICH_MESSAGES_ENABLED=true
```

默认启用。关闭后所有 `RichPage` 直接使用实体回退版本，不尝试 Rich API。开关只改变展示形式，不改变业务分支，便于发布后快速止损。

`.env.example` 同步记录该开关及默认值。运行时只把环境值 `1`、`true`、`yes`、`on`（忽略大小写）视为启用，其他值均视为关闭，避免配置解释不一致。

展示层使用 `logging.getLogger("xian.presentation")`。Rich 降级记录 warning，内容仅包含页面标识和 Telegram 错误类别。普通发送失败保留异常堆栈，由现有错误处理机制暴露。

## 迁移顺序

### 第一批

- 升级 aiogram 依赖；
- 建立消息内容模型和 `answer()`、`show()`、`send()`；
- 迁移 `/help`、`/me`；
- 迁移历练、秘境和 PvP 战报；
- 在 `.env.example` 记录环境开关，并增加回退与日志测试。

### 第二批

- 迁移其余交互型面板；
- 将合适的主动通知接入统一 `send()`；
- 保持现有列表上限、按钮布局和业务流程。

两批都只调整展示。第一批完成且全量测试通过后再进入第二批，便于控制回归范围。

## 测试

测试继续使用 pytest、pytest-asyncio、`monkeypatch` 和本地 FakeBot，不引入 `unittest.mock`。

渲染层测试覆盖：

- `str`、`Text` 和 `RichPage` 生成正确的 Telegram 参数；
- 实体消息始终显式使用 `parse_mode=None`；
- 玩家名或宗门名含 `<>&_*#[]()` 等字符时不产生格式注入或实体偏移错误；
- Rich HTML 的动态值正确转义，静态标题、列表和 `<details>` 保持完整；
- 关闭 `RICH_MESSAGES_ENABLED` 后不调用 Rich API；
- Rich 解析失败触发实体回退，未知异常和网络异常继续抛出；
- `message is not modified` 静默处理；
- 不可编辑消息只补发一次。

页面测试验证语义结构，不依赖脆弱的整段字符串快照：

- `/help` 包含四个分组和全部现有命令；
- `/me` 的境界、资源、六维、法宝功法和状态数据不丢失；
- 战报折叠区包含截断后的日志，胜负、奖励、血蓝和精力始终在折叠区外；
- Rich 版和实体回退版包含相同关键业务字段；
- 所有原有按钮文字、callback 数据和一次性令牌行为不变；
- 第二批页面保留余额、库存、价格、状态、成员和任务进度。

实现期间使用仓库 `.venv`。每批完成后都必须运行完整的 `python -m pytest`，不能只运行相关测试文件。另使用测试 Bot 在私聊中人工验证 Rich 开启、环境开关关闭、特殊字符名字、战报展开和按钮编辑。

## 验收标准

- 重点页面具有清晰标题、分区和列表，不再依赖横线字符模拟层级；
- Telegram 不出现 `can't parse entities`；
- Rich Message 失败时玩家仍能看到完整实体版本；
- 页面按钮和业务结果与改造前一致；
- 第一批和第二批结束时全量测试均为绿色。

## 非目标

本次不实现：

- 列表分页、消息拆分、图片或媒体卡片；
- 彩色按钮、自定义 emoji 或 Mini App；
- 游戏数值、业务文案含义或修仙口吻重写；
- 数据库迁移、服务层重构或 callback 协议变更。
