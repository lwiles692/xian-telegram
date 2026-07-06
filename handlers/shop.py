"""/shop —— NPC 商店：首页（摘要 + 分类入口）+ 分类页 + 回收页（#30）。"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config.items import ITEMS, item_name, sell_price
from config.shop import SHOP_ITEMS, goods_for_realm, shop_price
from handlers.common import (NEED_START, action_callback_data, append_main_menu_return,
                             consume_action_callback, guard_private_callback,
                             guard_private_message, section_back_markup, show)
from services import character, shop

router = Router()

# 分类口径（#30）：材料/丹方图纸直接按 items.type；丹药与突破同为 pill，
# 无法只靠 type 区分，故用 key 集合把境界突破相关丹药单列一类。
BREAKTHROUGH_KEYS = {"筑基丹", "金丹", "元婴丹", "洗髓丹"}
# (cat_id, 分类标题, 首页入口按钮文字)；顺序即首页计数与入口的展示顺序。
SHOP_CATEGORIES = [
    ("material", "材料", "买材料"),
    ("pill", "丹药", "买丹药"),
    ("breakthrough", "突破", "买突破"),
    ("recipe", "丹方图纸", "买配方"),
]
_CAT_TITLE = {cat: title for cat, title, _ in SHOP_CATEGORIES}


def _category_of(key: str) -> str:
    if key in BREAKTHROUGH_KEYS:
        return "breakthrough"
    return ITEMS.get(key, {}).get("type", "")


def _grouped_goods(realm: int) -> dict:
    """按分类归并当前境界可购商品，保留 SHOP_ITEMS 原始顺序。"""
    groups = {cat: [] for cat, _, _ in SHOP_CATEGORIES}
    for key, good in goods_for_realm(realm):
        cat = _category_of(key)
        if cat in groups:
            groups[cat].append((key, good))
    return groups


def _half_tag(key: str, good: dict, realm: int) -> str:
    """炼气期半价标记（#28）；筑基后或非半价物品为空串。"""
    if good.get("qi_half") and shop_price(key, realm) < good["price"]:
        return "（炼气期半价）"
    return ""


async def _sellable(user_id: int):
    inv = await character.inventory(user_id, bound=0)
    return [(key, qty) for key, qty in inv if sell_price(key) > 0]


def _stamina_button_text(offer: dict) -> str:
    if offer["status"] == "buy_limit":
        return f"购买精力（今日已达上限 {offer['limit']} 次）"
    return f"购买精力（🪙{offer['cost']} / ⚡{offer['gain']}）"


def _clamp_qty(qty: int, lo: int, hi: int) -> int:
    """将数量夹在合法区间内。"""
    return max(lo, min(hi, int(qty)))


def _back_markup() -> InlineKeyboardMarkup:
    """交易结果页的去处：回商店首页或回主菜单。"""
    return section_back_markup("↩️ 返回商店", "nav:shop")


async def render_shop(user_id: int, now: int | None = None):
    """商店首页：摘要 + 精力购买 + 分类入口 + 返回主菜单。"""
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    groups = _grouped_goods(char.realm)
    sellable = await _sellable(user_id)
    offer = await shop.stamina_buy_offer(user_id, now=now)

    lines = ["🪙 NPC 商店", f"灵石：{char.spirit_stone}", ""]
    if offer["status"] == "buy_limit":
        lines.append(f"⚡ 购买精力：今日已达上限（{offer['limit']} 次）")
    else:
        lines.append(
            f"⚡ 购买精力：🪙{offer['cost']} → ⚡{offer['gain']}"
            f"（今日 {offer['nth'] - 1}/{offer['limit']}）")
    counts = [f"{title} {len(groups[cat])}" for cat, title, _ in SHOP_CATEGORIES if groups[cat]]
    lines.append("🛒 可购：" + (" · ".join(counts) if counts else "暂无"))
    if sellable:
        lines.append(f"♻️ 可回收：{len(sellable)} 种")

    # 首行保持精力按钮（render 测试依赖 [0][0]）；分类入口每行两枚。
    rows = [[InlineKeyboardButton(
        text=_stamina_button_text(offer),
        callback_data=await action_callback_data(user_id, "shop:stamina"))]]
    entries = [InlineKeyboardButton(text=verb, callback_data=f"shop:cat:{cat}")
               for cat, _, verb in SHOP_CATEGORIES if groups[cat]]
    if sellable:
        entries.append(InlineKeyboardButton(text="卖物品", callback_data="shop:cat:sell"))
    rows += [entries[i:i + 2] for i in range(0, len(entries), 2)]
    append_main_menu_return(rows)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def render_category(user_id: int, cat: str, now: int | None = None):
    """分类页：列出该类可购商品及价格；按钮文字自带价格。"""
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    if cat == "sell":
        return await _render_sell(user_id, now=now)
    goods = _grouped_goods(char.realm).get(cat, [])
    if cat not in _CAT_TITLE or not goods:
        return await render_shop(user_id, now=now)

    lines = [f"🪙 {_CAT_TITLE[cat]}"]
    btns = []
    for key, good in goods:
        price = shop_price(key, char.realm)
        lines.append(f"- {item_name(key)}：{price} 灵石{_half_tag(key, good, char.realm)}")
        btns.append(InlineKeyboardButton(
            text=f"{item_name(key)} {price}",
            callback_data=await action_callback_data(user_id, f"shop:buy:{key}")))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="↩️ 返回商店", callback_data="nav:shop")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_sell(user_id: int, now: int | None = None):
    sellable = await _sellable(user_id)
    if not sellable:
        return await render_shop(user_id, now=now)
    lines = ["🪙 回收"]
    btns = []
    for key, qty in sellable:
        unit = sell_price(key)
        lines.append(f"- {item_name(key)}×{qty}：{unit} 灵石/个")
        btns.append(InlineKeyboardButton(
            text=f"卖 {item_name(key)} {unit}",
            callback_data=await action_callback_data(user_id, f"shop:sell:{key}")))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="↩️ 返回商店", callback_data="nav:shop")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def render_buy_editor(user_id: int, key: str, qty: int):
    """购买数量编辑面板。"""
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    good = SHOP_ITEMS.get(key)
    if not good or char.realm < good["realm"]:
        return await render_category(user_id, _category_of(key))
    unit = shop_price(key, char.realm)
    max_qty = max(1, char.spirit_stone // unit)
    qty = _clamp_qty(qty, 1, max_qty)
    total = unit * qty
    cat = _category_of(key)
    rows = [
        [InlineKeyboardButton(
            text="➖ 1",
            callback_data=await action_callback_data(user_id, f"shop:bqty:{key}:{qty - 1}")),
         InlineKeyboardButton(
            text="➕ 1",
            callback_data=await action_callback_data(user_id, f"shop:bqty:{key}:{qty + 1}")),
         InlineKeyboardButton(
            text="最大",
            callback_data=await action_callback_data(user_id, f"shop:bqty:{key}:{max_qty}"))],
        [InlineKeyboardButton(
            text=f"✅ 确认购买（{qty} 件 / {total} 灵石）",
            callback_data=await action_callback_data(user_id, f"shop:bdo:{key}:{qty}"))],
        [InlineKeyboardButton(text=f"↩️ 返回{_CAT_TITLE[cat]}", callback_data=f"shop:cat:{cat}")],
    ]
    text = "\n".join([
        f"🪙 购买 {item_name(key)}",
        f"单价：{unit} 灵石",
        f"数量：{qty}",
        f"总价：{total} 灵石（持有 {char.spirit_stone}）",
    ])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def render_sell_editor(user_id: int, key: str, qty: int):
    """回收数量编辑面板。"""
    char = await character.get(user_id)
    if not char:
        return NEED_START, None
    inv = dict(await character.inventory(user_id, bound=0))
    max_qty = inv.get(key, 0)
    if max_qty == 0:
        return await _render_sell(user_id)
    unit = sell_price(key)
    if unit <= 0:
        return await _render_sell(user_id)
    qty = _clamp_qty(qty, 1, max_qty)
    gain = unit * qty
    rows = [
        [InlineKeyboardButton(
            text="➖ 1",
            callback_data=await action_callback_data(user_id, f"shop:sqty:{key}:{qty - 1}")),
         InlineKeyboardButton(
            text="➕ 1",
            callback_data=await action_callback_data(user_id, f"shop:sqty:{key}:{qty + 1}")),
         InlineKeyboardButton(
            text="最大",
            callback_data=await action_callback_data(user_id, f"shop:sqty:{key}:{max_qty}"))],
        [InlineKeyboardButton(
            text=f"✅ 确认回收（{qty} 件 / {gain} 灵石）",
            callback_data=await action_callback_data(user_id, f"shop:sdo:{key}:{qty}"))],
        [InlineKeyboardButton(text="↩️ 返回回收", callback_data="shop:cat:sell")],
    ]
    text = "\n".join([
        f"♻️ 回收 {item_name(key)}",
        f"单价：{unit} 灵石",
        f"数量：{qty}",
        f"总得款：{gain} 灵石（库存 {max_qty}）",
    ])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _result_text(res: dict) -> str:
    s = res["status"]
    if s == "ok" and "cost" in res:
        return f"购得 {res['item']}×{res['qty']}，耗灵石 {res['cost']}。"
    if s == "ok":
        return f"回收 {res['item']}×{res['qty']}，得灵石 {res['gain']}。"
    if s == "stamina_ok":
        text = f"耗灵石 {res['cost']}，精力 +{res['gain']}（{res['stamina']}/{res['cap']}）。"
        if res.get("limit"):
            text += f"今日第 {res.get('nth')}/{res['limit']} 次"
            if res.get("next_cost"):
                text += f"，下次需 {res['next_cost']} 灵石"
            text += "。"
        return text
    if s == "stamina_full":
        return "精力已满，暂不必购买。"
    if s == "buy_limit":
        return f"今日买精力已达上限（{res['limit']} 次），灵石买精力非长久之计，明日再来。"
    if s == "no_stone":
        return f"灵石不足（需 {res['need']}，余 {res['have']}）。"
    if s == "no_item":
        return f"储物袋中 {res['item']} 不足，现有 {res['have']}。"
    if s == "locked":
        return "境界未至，店主暂不售此物。"
    if s == "missing":
        return NEED_START
    return "店主摇头，此物暂不可交易。"


@router.message(Command("shop"))
async def cmd_shop(message: Message):
    if await guard_private_message(message):
        return
    text, markup = await render_shop(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "nav:shop")
async def cb_shop(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    text, markup = await render_shop(callback.from_user.id)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:cat:"))
async def cb_category(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    cat = callback.data.split(":", 2)[2]
    text, markup = await render_category(callback.from_user.id, cat)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:buy:"))
async def cb_buy(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("shop:buy:"):
        return
    key = action.split(":", 2)[2]
    text, markup = await render_buy_editor(callback.from_user.id, key, 1)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:sell:"))
async def cb_sell(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("shop:sell:"):
        return
    key = action.split(":", 2)[2]
    text, markup = await render_sell_editor(callback.from_user.id, key, 1)
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:bqty:"))
async def cb_shop_bqty(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("shop:bqty:"):
        return
    value = action.split(":", 2)[2]
    key, qty_str = value.rsplit(":", 1)
    text, markup = await render_buy_editor(callback.from_user.id, key, int(qty_str))
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:bdo:"))
async def cb_shop_bdo(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("shop:bdo:"):
        return
    value = action.split(":", 2)[2]
    key, qty_str = value.rsplit(":", 1)
    res = await shop.buy(callback.from_user.id, key, int(qty_str))
    await show(callback, _result_text(res), _back_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("shop:sqty:"))
async def cb_shop_sqty(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("shop:sqty:"):
        return
    value = action.split(":", 2)[2]
    key, qty_str = value.rsplit(":", 1)
    text, markup = await render_sell_editor(callback.from_user.id, key, int(qty_str))
    await show(callback, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("shop:sdo:"))
async def cb_shop_sdo(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    action = await consume_action_callback(callback)
    if not action or not action.startswith("shop:sdo:"):
        return
    value = action.split(":", 2)[2]
    key, qty_str = value.rsplit(":", 1)
    res = await shop.sell(callback.from_user.id, key, int(qty_str))
    await show(callback, _result_text(res), _back_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("shop:stamina:"))
async def cb_buy_stamina(callback: CallbackQuery):
    if await guard_private_callback(callback):
        return
    if await consume_action_callback(callback) != "shop:stamina":
        return
    res = await shop.buy_stamina(callback.from_user.id)
    await show(callback, _result_text(res), _back_markup())
    await callback.answer()
