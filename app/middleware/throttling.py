import time
from typing import Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5, cleanup_interval: int = 300):
        self.rate_limit = rate_limit
        self.user_times: dict[int, float] = {}
        self.last_cleanup = time.monotonic()
        self.cleanup_interval = cleanup_interval

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, any]], Awaitable[any]],
        event: Message | CallbackQuery,
        data: dict[str, any],
    ) -> any:
        user_id = event.from_user.id if event.from_user else 0
        now = time.monotonic()

        if now - self.last_cleanup > self.cleanup_interval:
            cutoff = now - 60
            self.user_times = {uid: t for uid, t in self.user_times.items() if t > cutoff}
            self.last_cleanup = now

        if now - self.user_times.get(user_id, 0) < self.rate_limit:
            return
        self.user_times[user_id] = now
        return await handler(event, data)
