# Rich Message 404 回退设计

## 背景

PR #86 已在 `TelegramBadRequest` 表示的 Rich 格式错误或能力错误时回退到普通实体消息。但当 Telegram Bot API 端点尚不支持 `sendRichMessage` 时，HTTP 404 会被 aiogram 映射为 `TelegramNotFound`，当前代码会直接抛出，无法兑现“接口不支持时降级”的约定。

生产服务器使用 Python 3.11.2，满足 aiogram 3.29.1 的 Python 版本要求，本次不调整依赖或运行时声明。

## 目标

- Rich 回复和主动发送收到 `TelegramNotFound` 时，改发语义一致的普通实体消息。
- 降级日志仍只记录页面标识与“接口不支持”类别，不记录玩家名或正文。
- 现有 Rich 格式错误回退、未知 `TelegramBadRequest` 继续抛出、网络与限流异常继续抛出的行为保持不变。

## 方案

在 `bot.presentation.answer()` 和 `send()` 的 Rich API 调用处单独捕获 `TelegramNotFound`，记录“接口不支持”警告后切换到 `RichPage.fallback`。

不扩大为捕获所有 `TelegramAPIError`。如果 404 实际源于不可达资源，后续普通消息发送仍会按原异常自然失败，因此不会把真实故障静默吞掉。

`show()` 继续沿用现有逻辑：它调用的是始终存在的 `editMessageText`，Rich 参数不受支持时由现有 `TelegramBadRequest` 能力错误分支处理。

## 测试

在 `tests/test_presentation.py` 增加真实 `TelegramNotFound` 类型的回归测试，覆盖：

- `answer()` 先尝试 Rich 回复，再发送普通实体回退；
- `send()` 先尝试 Rich 主动发送，再发送普通实体回退；
- 两次降级均记录页面标识和“接口不支持”；
- 既有未知异常不吞掉测试保持通过。

实现遵循测试先行：新增测试并确认因 `TelegramNotFound` 未被捕获而失败，再做最小代码修改使其通过，最后运行全量测试。
