# 商店数量选择器

## 背景
NPC 商店（`/shop`）当前买卖只能单件操作：点商品按钮 → 直接买/卖 1 件。
`services/shop.py` 的 `buy(qty=1)` / `sell(qty=1)` 早已有 qty 参数，缺口仅在 UI。

参考坊市挂单的 `render_price_editor` 交互机制（`handlers/market.py`），为买/卖加入数量编辑面板。

## 设计决策（已与用户确认）
- **范围**：买 + 卖都加数量选择
- **步进按钮**：三键 `[-1][+1][最大]`（仿坊市极简风）
- **入口**：点商品按钮 → 直接进数量编辑器（仿坊市点物品 → 进价格编辑器）
- **Service 层**：零改动

## 流程

```
[分类商品列表] ──shop:buy:{key}──> [购买数量编辑器（默认 qty=1）]
                                       │
                            [-1][+1][最大]
                            (shop:bqty:{key}:{n}, token, 重绘)
                                       │
                            ✅ 确认购买 {n} 件（总价 {n*单价}）
                            (shop:bdo:{key}:{n}, token, 落库)
```

卖出对称：`shop:sell:{key}` → `shop:sqty:{key}:{n}`（步进）→ `shop:sdo:{key}:{n}`（确认）。

## 回调命名空间

| 回调 | 用途 | 行为 |
|---|---|---|
| `shop:buy:{key}` | 进入购买编辑器 | **改**：从"立即买 1 件"→"开编辑器（默认 1）" |
| `shop:bqty:{key}:{qty}` | 购买数量步进（重绘） | 新增 |
| `shop:bdo:{key}:{qty}` | 购买确认（落库） | 新增 |
| `shop:sell:{key}` | 进入卖出编辑器 | **改**：从"立即卖 1 件"→"开编辑器（默认 1）" |
| `shop:sqty:{key}:{qty}` | 卖出数量步进（重绘） | 新增 |
| `shop:sdo:{key}:{qty}` | 卖出确认（落库） | 新增 |

解析：`action.split(":", 2)[2]` 取 `value`，再 `value.rsplit(":", 1)` 取 `(key, qty)`（仿 market）。
key 不会含 `:`（物品名为中文），rsplit 安全。

## 数量边界（clamp）

- **购买**：`max_qty = max(1, spirit_stone // shop_price(key, realm))`（买得起，至少 1）；clamp(qty, 1, max_qty)
  - 灵石不足 1 件时，最大=1，确认走 service → `no_stone` 错误（标准反馈）
- **卖出**：`max_qty = item_qty_conn(bound=0)`（非绑定库存）
  - 库存为 0（竞态）→ 重定向回回收分类页；否则 clamp(qty, 1, max_qty)

## 新增 handler 函数

- `render_buy_editor(user_id, key, qty) -> (text, markup)` —— 仿 `render_price_editor`
- `render_sell_editor(user_id, key, qty) -> (text, markup)`
- `cb_shop_bqty` / `cb_shop_bdo` / `cb_shop_sqty` / `cb_shop_sdo` —— 4 个新回调路由

## 修改点

- `handlers/shop.py`：
  - `cb_buy` 改为调 `render_buy_editor(uid, key, 1)`（不再直接 `shop.buy`）
  - `cb_sell` 改为调 `render_sell_editor(uid, key, 1)`（不再直接 `shop.sell`）
  - 新增 2 个 render 函数 + 4 个回调路由 + `_clamp_qty` 辅助
  - imports：补 `SHOP_ITEMS`（config.shop），按需补 `character.inventory` 用法
- `services/shop.py`：**零改动**
- `tests/test_economy.py`：现有断言（`shop:buy:{key}:{token}` 出现在分类页）仍成立；新增编辑器/步进/确认流测试

## 编辑器面板示例（购买）

```
🪙 购买 灵草
单价：10 灵石
数量：3
总价：30 灵石（持有 1200）

[➖ 1] [➕ 1] [最大]
[✅ 确认购买（3 件 / 30 灵石）]
[↩️ 返回材料]
```

## 不做（YAGNI）
- 不加 `-10/+10`（用户选了三键极简）
- 不加预设档 `[1/5/10]`
- 不改 service 层签名或返回 dict
- 不动 `shop:stamina` 精力购买流（单次性，无需数量）
