import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, BotCommand, BotCommandScopeDefault

from app.config import config
from app.middleware.throttling import ThrottlingMiddleware
from app.handlers import start, profile, payment, admin

logger = logging.getLogger(__name__)

if config.BOT_PROXY:
    session = AiohttpSession(proxy=config.BOT_PROXY)
    bot = Bot(token=config.BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
else:
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

dp = Dispatcher()


async def setup_bot_commands():
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="menu", description="📋 Главное меню"),
    ]
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())
    await bot.set_my_description(
        description="🔒 VPN-бот — защищённый интернет без ограничений. "
                    "Покупай подписку, получай доступ к серверам по всему миру."
    )
    await bot.set_my_short_description(
        short_description="🔒 VPN-бот. Попробуй бесплатно 3 дня."
    )
    logger.info("Bot commands and description set.")


@dp.error()
async def error_handler(event: ErrorEvent):
    error_text = str(event.exception)
    if "message is not modified" in error_text or "message to edit not found" in error_text:
        logger.debug(f"Silent edit error: {error_text}")
        return
    logger.error(f"Unhandled error: {error_text}", exc_info=event.exception)


dp.message.middleware(ThrottlingMiddleware())
dp.callback_query.middleware(ThrottlingMiddleware())

dp.include_router(start.router)
dp.include_router(profile.router)
dp.include_router(payment.router)
dp.include_router(admin.router)
