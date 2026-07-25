import asyncio
import logging

from aiohttp import web

from app.bot import bot, dp, setup_bot_commands
from app.config import config
from app.database import init_db, close_db, deactivate_expired_subscriptions
from app.web.subscription import setup_subscription_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SUB_PORT = config.SUB_PORT

EXPIRY_CHECK_INTERVAL = 60  # seconds


async def periodic_expiry_check():
    """Every minute, deactivate expired subscriptions."""
    while True:
        try:
            await deactivate_expired_subscriptions()
        except Exception as e:
            logger.error(f"Expiry check error: {e}")
        await asyncio.sleep(EXPIRY_CHECK_INTERVAL)


async def on_startup():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized.")

    await setup_bot_commands()

    if config.WEBHOOK_HOST:
        await bot.set_webhook(
            url=config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logger.info(f"Webhook set to {config.WEBHOOK_URL}")
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted, using polling.")


async def on_shutdown():
    if config.WEBHOOK_HOST:
        await bot.delete_webhook()
    await close_db()
    await bot.session.close()
    logger.info("Bot shutdown.")


async def run_subscription_server():
    """Запускает веб-сервер для подписок V2RayTun"""
    app = web.Application()
    setup_subscription_routes(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=SUB_PORT)
    await site.start()
    logger.info(f"Subscription server running on http://0.0.0.0:{SUB_PORT}")
    logger.info(f"Example sub link: http://IP:{SUB_PORT}/sub/TOKEN")
    return runner


async def main():
    await on_startup()

    # Запускаем подписочный сервер
    sub_runner = await run_subscription_server()

    # Запускаем фоновую задачу проверки истекающих подписок
    expiry_task = asyncio.create_task(periodic_expiry_check())

    try:
        logger.info("Starting bot polling...")
        await dp.start_polling(bot)
    finally:
        expiry_task.cancel()
        await sub_runner.cleanup()
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
