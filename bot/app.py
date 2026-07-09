from __future__ import annotations

"""bot 启动：加载配置、初始化 DB、注册 Router、polling。"""

import logging
import os

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from handlers import (ascension, auction, bag, bonds, boss, craft, cultivate, daily, dao_path,
                      dungeon, explore, help as help_h, market, me, pvp,
                      rank, sect, sect_war, shop, skills, start, weekly_events)
from handlers.common import cleanup_callback_tokens
from models import db
from handlers import quest
from services import (activity, bonds as bonds_service, character, notifications,
                      season, social, world_boss)
from services import auction as auction_service
from services import market as market_service
from services import pvp as pvp_service
from services import sect_war as sect_war_service


class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and not getattr(user, "is_bot", False):
            username = user.username or user.full_name or str(user.id)
            await character.touch_activity(user.id, username)
            chat = (data.get("event_chat") or getattr(event, "chat", None)
                    or getattr(getattr(event, "message", None), "chat", None))
            chat_type = str(getattr(chat, "type", "")).lower()
            if chat and not (chat_type == "private" or chat_type.endswith(".private")):
                await world_boss.remember_chat(chat.id, getattr(chat, "title", None))
                await world_boss.remember_cultivator(chat.id, user.id)
        return await handler(event, data)

_COMMANDS = [
    BotCommand(command="start", description="踏入仙途 / 测灵根"),
    BotCommand(command="me", description="查看道行"),
    BotCommand(command="cultivate", description="闭关 / 出关"),
    BotCommand(command="explore", description="历练刷怪"),
    BotCommand(command="dungeon", description="秘境副本"),
    BotCommand(command="craft", description="炼丹炼器"),
    BotCommand(command="skills", description="法宝 / 功法"),
    BotCommand(command="shop", description="NPC 商店"),
    BotCommand(command="pvp", description="群内切磋"),
    BotCommand(command="rank", description="天梯排行"),
    BotCommand(command="boss", description="世界 Boss"),
    BotCommand(command="sect", description="宗门"),
    BotCommand(command="daily", description="每日签到"),
    BotCommand(command="quest", description="悬赏任务"),
    BotCommand(command="master", description="师徒"),
    BotCommand(command="partner", description="道侣共修"),
    BotCommand(command="bag", description="储物袋"),
    BotCommand(command="path", description="道途 / 转修"),
    BotCommand(command="ascension", description="飞升试炼"),
    BotCommand(command="weekly", description="周活动副本"),
    BotCommand(command="market", description="玩家坊市"),
    BotCommand(command="auction", description="拍卖行"),
    BotCommand(command="sectwar", description="宗门战据点"),
    BotCommand(command="help", description="指南"),
]


async def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("缺少 BOT_TOKEN：请复制 .env.example 为 .env 并填入 token。")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    await db.init_db()

    bot = Bot(token=token)
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(world_boss.scheduled_spawn, "cron", hour=20, minute=0, args=[bot])
    # 周日 23:40 被动结算师父周活跃回报，错开 PvP/赛季/宗门战结算（spec-v3 §4.3）。
    scheduler.add_job(
        bonds_service.settle_weekly_mentor_activity,
        "cron",
        day_of_week="sun",
        hour=23,
        minute=40)
    # 周日 23:55（仍属当周 %W）结算 PvP 周榜奖池（#14）。
    scheduler.add_job(pvp_service.settle_weekly, "cron", day_of_week="sun", hour=23, minute=55)
    # 月末 23:50 结算月赛季：向天梯参与者发绑定称号 + 道行（幂等，#A2）。
    scheduler.add_job(season.settle_monthly, "cron", day="last", hour=23, minute=50)
    # 月末 23:45 结算据点战赛季：积分最高宗门夺魁，成员得绑定道行（幂等，spec §8.1）。
    scheduler.add_job(sect_war_service.settle_season, "cron", day="last", hour=23, minute=45)
    scheduler.add_job(cleanup_callback_tokens, "interval", hours=1)
    scheduler.add_job(bonds_service.expire_pending, "interval", hours=1)
    scheduler.add_job(market_service.notify_recent_listings, "interval", hours=1, args=[bot])
    scheduler.add_job(auction_service.notify_recent_auctions, "interval", hours=1, args=[bot])
    scheduler.add_job(activity.cleanup, "interval", hours=6)
    scheduler.add_job(auction_service.notify_closing_auctions, "interval", minutes=1, args=[bot])
    scheduler.add_job(auction_service.notify_closing_watchers, "interval", minutes=1)
    scheduler.add_job(auction_service.settle_due, "interval", minutes=1)
    scheduler.add_job(notifications.notify_ready_actions, "interval", minutes=1, args=[bot])
    scheduler.add_job(social.flush_broadcasts, "interval", minutes=1, args=[bot])
    scheduler.start()
    dp = Dispatcher()
    dp.update.middleware(ActivityMiddleware())
    for module in (start, me, cultivate, explore, dungeon, craft, skills, shop, bag,
                   quest, bonds, dao_path, ascension, weekly_events, market, auction, sect_war,
                   pvp, rank, boss, sect, daily, help_h):
        dp.include_router(module.router)

    await bot.set_my_commands(_COMMANDS)
    logging.getLogger("xian").info("问道 bot 启动，开始 polling……")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await db.close_db()
