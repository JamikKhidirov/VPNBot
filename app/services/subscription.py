import logging
from datetime import datetime, timedelta, timezone

from app.config import config
from app.database import (
    get_user, get_user_by_id, get_or_create_user, get_active_subscription,
    create_subscription, get_all_servers, get_plan, get_plans, update_user,
    deactivate_expired_subscriptions, get_active_configs,
)
from app.services.v2ray import v2ray_service

logger = logging.getLogger(__name__)


class SubscriptionService:

    async def _create_configs_for_all_servers(
        self, user_id: int, subscription_id: int, days: int,
    ) -> list[dict]:
        """Создаёт конфиги на всех активных серверах."""
        servers = await get_all_servers()
        active_servers = [s for s in servers if s.is_active]
        configs = []

        for srv in active_servers:
            try:
                cfg = await v2ray_service.create_user_config(
                    user_id=user_id, server_id=srv.id,
                    subscription_id=subscription_id,
                    duration_days=days,
                    server_host=srv.host,
                    server_port=srv.port,
                )
                configs.append(cfg)
                logger.info(
                    f"CONFIG_CREATED: user_id={user_id} "
                    f"server_id={srv.id} server={srv.host}"
                )
            except Exception as e:
                logger.error(
                    f"CONFIG_FAILED: user_id={user_id} "
                    f"server_id={srv.id} error={e}"
                )

        return configs

    async def activate_trial(self, telegram_id: int) -> dict:
        user = await get_user(telegram_id)
        if not user:
            return {"success": False, "error": "Пользователь не найден"}
        if user.trial_used:
            return {"success": False, "error": "Пробный период уже был использован"}

        trial_plan = await get_plan("trial")
        if not trial_plan:
            return {"success": False, "error": "Пробный тариф не настроен"}

        servers = await get_all_servers()
        active_servers = [s for s in servers if s.is_active]
        if not active_servers:
            return {"success": False, "error": "Нет доступных серверов"}

        end_date = datetime.now(timezone.utc) + timedelta(days=trial_plan.days)
        subscription = await create_subscription(
            user_id=user.id, plan="trial", end_date=end_date,
        )
        await update_user(telegram_id, trial_used=True)

        configs = await self._create_configs_for_all_servers(
            user_id=user.id,
            subscription_id=subscription.id,
            days=trial_plan.days,
        )

        return {
            "success": True,
            "subscription": subscription,
            "configs": configs,
            "servers_count": len(configs),
        }

    async def purchase_subscription(self, telegram_id: int, plan_code: str) -> dict:
        user = await get_user(telegram_id)
        if not user:
            return {"success": False, "error": "Пользователь не найден"}

        plan = await get_plan(plan_code)
        if not plan:
            return {"success": False, "error": "Неверный тариф"}

        if plan.price == 0 and plan_code == "trial":
            return await self.activate_trial(telegram_id)

        servers = await get_all_servers()
        active_servers = [s for s in servers if s.is_active]
        if not active_servers:
            return {"success": False, "error": "Нет доступных серверов"}

        end_date = datetime.now(timezone.utc) + timedelta(days=plan.days)
        subscription = await create_subscription(
            user_id=user.id, plan=plan_code, end_date=end_date,
        )

        configs = await self._create_configs_for_all_servers(
            user_id=user.id,
            subscription_id=subscription.id,
            days=plan.days,
        )

        return {
            "success": True,
            "subscription": subscription,
            "configs": configs,
            "servers_count": len(configs),
        }

    async def activate_subscription_after_payment(self, user_id: int, plan_code: str) -> dict:
        plan = await get_plan(plan_code)
        if not plan:
            return {"success": False, "error": "Неверный тариф"}

        servers = await get_all_servers()
        active_servers = [s for s in servers if s.is_active]
        if not active_servers:
            return {"success": False, "error": "Нет доступных серверов"}

        active_sub = await get_active_subscription(user_id)

        if plan.price == 0 and plan_code == "trial":
            user = await get_user_by_id(user_id)
            if user and user.trial_used:
                return {"success": False, "error": "Пробный период уже был использован"}

        if active_sub:
            end_date = active_sub.end_date + timedelta(days=plan.days)
        else:
            end_date = datetime.now(timezone.utc) + timedelta(days=plan.days)

        subscription = await create_subscription(
            user_id=user_id, plan=plan_code, end_date=end_date,
        )
        if plan_code == "trial":
            user_obj = await get_user_by_id(user_id)
            if user_obj:
                await update_user(user_obj.telegram_id, trial_used=True)

        configs = await self._create_configs_for_all_servers(
            user_id=user_id,
            subscription_id=subscription.id,
            days=plan.days,
        )

        return {
            "success": True,
            "subscription": subscription,
            "configs": configs,
            "servers_count": len(configs),
            "new_end_date": end_date,
        }

    async def get_user_status(self, telegram_id: int) -> dict:
        user = await get_user(telegram_id)
        if not user:
            return {"exists": False}

        active_sub = await get_active_subscription(user.id)
        configs = []
        if active_sub:
            configs = await get_active_configs(user.id)

        status = "inactive"
        days_left = 0
        if active_sub:
            now = datetime.now(timezone.utc)
            end = active_sub.end_date
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end > now:
                status = "active"
                days_left = (end - now).days
            elif active_sub.plan == "trial":
                status = "trial_expired"
            else:
                status = "expired"

        return {
            "exists": True,
            "user": user,
            "status": status,
            "days_left": days_left,
            "active_subscription": active_sub,
            "configs": configs,
            "trial_used": user.trial_used,
        }

    async def cleanup_expired(self):
        await deactivate_expired_subscriptions()

    async def get_plans(self) -> list:
        return await get_plans()


subscription_service = SubscriptionService()
