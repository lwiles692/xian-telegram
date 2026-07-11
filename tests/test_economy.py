"""经济回归测试(#16):买精力阶梯价/每日上限。

补灵丹（原回精力，#16 有每日上限）已于 #24 改为回法力、脱离经济，相关用例移至 test_vitals。
#28：商店在炼气期供应疗伤丹/补灵丹（筑基前半价、筑基后全价），相关用例见文件末尾。
"""
import time

import pytest
import pytest_asyncio

from config import shop as shop_cfg
from handlers.common import action_callback_data
from handlers import shop as shop_handler
from models import db
from services import character, items, shop

DAY = 24 * 3600


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    await db.init_db(str(tmp_path / "econ-test.db"))
    try:
        yield
    finally:
        await db.close_db()


async def _drain(uid):
    """把精力清零以便连续购买（不动 stamina_at，避免触发自然恢复）。"""
    await db.execute("UPDATE characters SET stamina=0 WHERE user_id=?", (uid,))


@pytest.mark.asyncio
async def test_buy_stamina_escalates_and_caps(temp_db):
    uid = 5001
    await character.create(uid, "tester")
    await character.set_progress(uid, 3, 0, 0)  # 元婴，基价最高便于看翻倍
    await db.execute(
        "UPDATE characters SET stamina=0, stamina_at=1000, spirit_stone=10_000_000 WHERE user_id=?",
        (uid,))

    costs = []
    for _ in range(shop_cfg.STAMINA_BUY_DAILY_LIMIT):
        await _drain(uid)
        res = await shop.buy_stamina(uid, now=1000)
        assert res["status"] == "stamina_ok"
        costs.append(res["cost"])

    # 当日第 n 次价格按 2 的幂翻倍递增。
    assert costs == [shop_cfg.stamina_buy_cost(3, n) for n in range(1, len(costs) + 1)]
    assert costs[1] == costs[0] * 2 and costs[2] == costs[1] * 2

    # 触达每日上限后拒绝。
    await _drain(uid)
    assert (await shop.buy_stamina(uid, now=1000))["status"] == "buy_limit"

    # 跨天重置回首买价。
    await db.execute("UPDATE characters SET stamina=0, stamina_at=? WHERE user_id=?", (1000 + DAY, uid))
    res = await shop.buy_stamina(uid, now=1000 + DAY)
    assert res["status"] == "stamina_ok"
    assert res["cost"] == shop_cfg.stamina_buy_cost(3, 1)


@pytest.mark.asyncio
async def test_render_shop_shows_next_stamina_buy_cost(temp_db):
    uid = 5003
    now = 1000
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    await character.create(uid, "tester")
    await character.set_progress(uid, 3, 0, 0)

    await db.execute(
        "UPDATE characters SET stamina_buy_count=1, stamina_buy_day=? WHERE user_id=?",
        (today, uid))
    _, markup = await shop_handler.render_shop(uid, now=now)
    assert markup is not None
    assert markup.inline_keyboard[0][0].text == (
        f"购买精力（🪙{shop_cfg.stamina_buy_cost(3, 2)} / ⚡{shop_cfg.STAMINA_BUY_GAIN}）")

    await db.execute(
        "UPDATE characters SET stamina_buy_count=2, stamina_buy_day=? WHERE user_id=?",
        (today, uid))
    _, markup = await shop_handler.render_shop(uid, now=now)
    assert markup is not None
    assert markup.inline_keyboard[0][0].text == (
        f"购买精力（🪙{shop_cfg.stamina_buy_cost(3, 3)} / ⚡{shop_cfg.STAMINA_BUY_GAIN}）")
def test_huashen_lianxu_stamina_price_and_pills_not_in_shop():
    assert shop_cfg.stamina_buy_cost(4, 1) == 2800
    assert shop_cfg.stamina_buy_cost(4, 2) == 5600
    assert shop_cfg.stamina_buy_cost(5, 1) == 6000
    assert shop_cfg.stamina_buy_cost(5, 2) == 12000
    assert "化神丹" not in shop_cfg.SHOP_ITEMS
    assert "炼虚丹" not in shop_cfg.SHOP_ITEMS


@pytest.mark.asyncio
async def test_recovery_pills_buyable_in_qi_at_half_price(temp_db):
    """#28：炼气期能在商店买到疗伤丹/补灵丹（补给不再断档），且筑基前半价。"""
    uid = 5005
    await character.create(uid, "tester")  # 默认炼气期 realm 0
    await character.add_stone(uid, 1000)

    # 取价函数：炼气期半价（25/30），筑基起全价（50/60）。
    assert shop_cfg.shop_price("疗伤丹", 0) == 25
    assert shop_cfg.shop_price("补灵丹", 0) == 30
    assert shop_cfg.shop_price("疗伤丹", 1) == 50
    assert shop_cfg.shop_price("补灵丹", 1) == 60

    # 炼气期实买：不再返回 locked，按半价扣费并入袋。
    res = await shop.buy(uid, "疗伤丹")
    assert res["status"] == "ok" and res["cost"] == 25
    res = await shop.buy(uid, "补灵丹")
    assert res["status"] == "ok" and res["cost"] == 30
    assert await character.item_qty(uid, "疗伤丹") == 1
    assert await character.item_qty(uid, "补灵丹") == 1

    # 丹药分类页向炼气期玩家展示这两味并标注半价（#30 首页不再列单品）。
    text, _ = await shop_handler.render_category(uid, "pill")
    assert "疗伤丹：25 灵石（炼气期半价）" in text
    assert "补灵丹：30 灵石（炼气期半价）" in text


@pytest.mark.asyncio
async def test_recovery_pills_full_price_after_foundation(temp_db):
    """#28：筑基后恢复丹全价（50/60），保证 /craft 自炼仍更省。"""
    uid = 5006
    await character.create(uid, "tester")
    await character.set_progress(uid, 1, 0, 0)  # 筑基期 realm 1
    await character.add_stone(uid, 1000)

    res = await shop.buy(uid, "疗伤丹")
    assert res["status"] == "ok" and res["cost"] == 50
    res = await shop.buy(uid, "补灵丹")
    assert res["status"] == "ok" and res["cost"] == 60

    text, _ = await shop_handler.render_category(uid, "pill")
    assert "（炼气期半价）" not in text


def _datas(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


class _FakeChat:
    type = "private"


class _FakeMessage:
    def __init__(self):
        self.chat = _FakeChat()
        self.edits = []
        self.answers = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


class _FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class _FakeCallback:
    def __init__(self, user_id, data):
        self.data = data
        self.from_user = _FakeUser(user_id)
        self.message = _FakeMessage()
        self.bot = None
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


@pytest.mark.asyncio
async def test_shop_home_summary_entries_and_no_full_menu(temp_db):
    """#30：首页只展示摘要 + 精力 + 分类入口 + 返回主菜单，不再追加完整主菜单。"""
    uid = 5007
    await character.create(uid, "tester")  # 炼气期 realm 0
    await db.execute("DELETE FROM inventory WHERE user_id=?", (uid,))

    text, markup = await shop_handler.render_shop(uid)
    assert markup is not None
    # 炼气期可购：材料 2（灵草/兽皮）· 丹药 4 · 突破 1（筑基丹）；丹方此境界无。
    assert "🛒 可购：材料 2 · 丹药 4 · 突破 1" in text
    datas = _datas(markup)
    # 非空分类有入口，空分类（丹方）无入口；无可回收物时不显示卖物品。
    assert {"shop:cat:material", "shop:cat:pill", "shop:cat:breakthrough"} <= set(datas)
    assert "shop:cat:recipe" not in datas
    assert "shop:cat:sell" not in datas
    # 不再追加完整主菜单：除返回主菜单外不含其它 nav 项；保留单一返回主菜单。
    assert "nav:cultivate" not in datas and "nav:bag" not in datas
    assert markup.inline_keyboard[-1][-1].callback_data == "nav:menu"
    # 首行仍是精力按钮（render 测试契约）。
    assert markup.inline_keyboard[0][0].callback_data.startswith("shop:stamina:")

    # 持有可回收物后，首页出现卖物品入口。
    await shop.buy(uid, "疗伤丹")  # 疗伤丹可回收（sell 20）
    _, markup = await shop_handler.render_shop(uid)
    assert markup is not None
    text2, _ = await shop_handler.render_shop(uid)
    assert "shop:cat:sell" in _datas(markup)
    assert "♻️ 可回收：1 种" in text2


@pytest.mark.asyncio
async def test_shop_category_page_lists_goods_with_priced_buttons(temp_db):
    """#30：分类页列出该类商品及价格，按钮文字自带价格，并可返回商店。"""
    uid = 5008
    await character.create(uid, "tester")

    text, markup = await shop_handler.render_category(uid, "material")
    assert markup is not None
    assert "灵草" in text and "兽皮" in text
    assert "灵草 12" in _texts(markup)  # 按钮带价格
    assert any(d.startswith("shop:buy:灵草:") for d in _datas(markup))  # 沿用一次性 token
    assert markup.inline_keyboard[-1][-1].callback_data == "nav:shop"


@pytest.mark.asyncio
async def test_shop_sell_page_lists_sellables(temp_db):
    """#30：回收页展示可回收物、数量、单价，并能发起出售。"""
    uid = 5009
    await character.create(uid, "tester")
    await db.execute("DELETE FROM inventory WHERE user_id=?", (uid,))
    await shop.buy(uid, "疗伤丹")  # 入手一件可回收物（sell 20）

    text, markup = await shop_handler.render_category(uid, "sell")
    assert markup is not None
    assert "疗伤丹×1：20 灵石/个" in text
    assert "卖 疗伤丹 20" in _texts(markup)
    assert any(d.startswith("shop:sell:疗伤丹:") for d in _datas(markup))
    assert markup.inline_keyboard[-1][-1].callback_data == "nav:shop"


@pytest.mark.asyncio
async def test_render_buy_editor_shows_step_callbacks_and_clamps_to_max_qty(temp_db):
    uid = 5010
    await character.create(uid, "tester")
    await db.execute("UPDATE characters SET spirit_stone=100 WHERE user_id=?", (uid,))

    text, markup = await shop_handler.render_buy_editor(uid, "灵草", 99999)
    assert markup is not None
    datas = _datas(markup)

    assert "🪙 购买 灵草" in text
    assert "单价：12 灵石" in text
    assert "数量：8" in text
    assert "总价：96 灵石（持有 100）" in text
    assert any(d.startswith("shop:bqty:灵草:7:") for d in datas)    # ➖1
    assert any(d.startswith("shop:bqty:灵草:9:") for d in datas)    # ➕1
    assert any(d.startswith("shop:bqty:灵草:-2:") for d in datas)   # ➖10（越界，回调时会兜底夹到 1）
    assert any(d.startswith("shop:bqty:灵草:18:") for d in datas)   # ➕10
    assert any(d.startswith("shop:bqty:灵草:8:") for d in datas)    # 最大
    assert any(d.startswith("shop:bdo:灵草:8:") for d in datas)
    assert markup.inline_keyboard[-1][0].callback_data == "shop:cat:material"


@pytest.mark.asyncio
async def test_render_sell_editor_shows_step_callbacks_and_clamps_to_inventory(temp_db):
    uid = 5011
    await character.create(uid, "tester")
    await character.add_stone(uid, 1000)
    await shop.buy(uid, "疗伤丹", qty=3)

    text, markup = await shop_handler.render_sell_editor(uid, "疗伤丹", 99999)
    assert markup is not None
    datas = _datas(markup)

    assert "♻️ 回收 疗伤丹" in text
    assert "单价：20 灵石" in text
    assert "数量：3" in text
    assert "总得款：60 灵石（库存 3）" in text
    assert any(d.startswith("shop:sqty:疗伤丹:2:") for d in datas)   # ➖1
    assert any(d.startswith("shop:sqty:疗伤丹:4:") for d in datas)   # ➕1
    assert any(d.startswith("shop:sqty:疗伤丹:-7:") for d in datas)  # ➖10（越界，回调时会兜底夹到 1）
    assert any(d.startswith("shop:sqty:疗伤丹:13:") for d in datas)  # ➕10
    assert any(d.startswith("shop:sqty:疗伤丹:3:") for d in datas)   # 最大
    assert any(d.startswith("shop:sdo:疗伤丹:3:") for d in datas)
    assert markup.inline_keyboard[-1][0].callback_data == "shop:cat:sell"


@pytest.mark.asyncio
async def test_shop_buy_confirm_callback_buys_selected_quantity(temp_db):
    uid = 5012
    await character.create(uid, "tester")
    await db.execute("UPDATE characters SET spirit_stone=100 WHERE user_id=?", (uid,))

    data = await action_callback_data(uid, "shop:bdo:灵草:3")
    callback = _FakeCallback(uid, data)
    await shop_handler.cb_shop_bdo(callback)

    assert callback.answers == [(None, False)]
    assert callback.message.edits
    text, markup = callback.message.edits[-1]
    assert markup is not None
    assert text == "购得 灵草×3，耗灵石 36。"
    assert markup.inline_keyboard[0][0].callback_data == "nav:shop"
    assert await character.item_qty(uid, "灵草") == 3


@pytest.mark.asyncio
async def test_shop_sell_confirm_callback_sells_selected_quantity(temp_db):
    uid = 5013
    await character.create(uid, "tester")
    await character.add_stone(uid, 1000)
    await shop.buy(uid, "疗伤丹", qty=3)

    data = await action_callback_data(uid, "shop:sdo:疗伤丹:2")
    callback = _FakeCallback(uid, data)
    await shop_handler.cb_shop_sdo(callback)

    assert callback.answers == [(None, False)]
    assert callback.message.edits
    text, markup = callback.message.edits[-1]
    assert markup is not None
    assert text == "回收 疗伤丹×2，得灵石 40。"
    assert markup.inline_keyboard[0][0].callback_data == "nav:shop"
    assert await character.item_qty(uid, "疗伤丹") == 1


@pytest.mark.asyncio
async def test_shop_sell_excludes_bound_only_items(temp_db):
    """P2 回归：仅有绑定副本的可回收物品不应进入回收入口。

    背景：render_sell_editor 用 bound=0 读库存，但 _sellable 不过滤 bound，
    导致仅有绑定副本时点击回收按钮会回到 _render_sell 死循环。
    根因修复：_sellable 也按 bound=0 过滤，与 shop.sell 消费口径一致。
    """
    uid = 5014
    await character.create(uid, "tester")
    await db.execute("DELETE FROM inventory WHERE user_id=?", (uid,))
    # 仅放入绑定副本（bound=1）；疗伤丹 sell_price>0，但绑定版不可回收。
    await db.execute(
        "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,1,3)",
        (uid, "疗伤丹"))

    # 商店首页不应出现回收入口（无非绑定可回收物）。
    text, markup = await shop_handler.render_shop(uid)
    assert markup is not None
    assert "shop:cat:sell" not in _datas(markup)
    assert "可回收" not in text

    # 直接调 _sellable 也不应返回该物品。
    assert await shop_handler._sellable(uid) == []

    # 放入非绑定副本后，回收入口才出现。
    await db.execute(
        "INSERT INTO inventory(user_id, item_key, bound, qty) VALUES(?,?,0,1)",
        (uid, "疗伤丹"))
    text2, markup2 = await shop_handler.render_shop(uid)
    assert "shop:cat:sell" in _datas(markup2)
    assert "可回收：1 种" in text2
