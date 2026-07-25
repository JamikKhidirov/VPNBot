import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload

from app.database.engine import async_session
from app.database.models import User, Plan, Subscription, Payment, Server, VPNConfig


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


async def create_user(telegram_id: int, **kwargs) -> User:
    async with async_session() as session:
        user = User(telegram_id=telegram_id, **kwargs)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def update_user(telegram_id: int, **kwargs) -> User | None:
    async with async_session() as session:
        await session.execute(
            update(User).where(User.telegram_id == telegram_id).values(**kwargs)
        )
        await session.commit()
        return await get_user(telegram_id)


async def get_all_users() -> list[User]:
    async with async_session() as session:
        result = await session.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())


async def get_users_count() -> int:
    async with async_session() as session:
        result = await session.execute(select(func.count(User.id)))
        return result.scalar() or 0


async def get_active_users_count() -> int:
    async with async_session() as session:
        result = await session.execute(
            select(func.count(User.id)).where(
                User.id.in_(
                    select(Subscription.user_id).where(
                        Subscription.is_active == True,
                        Subscription.end_date > datetime.now(timezone.utc),
                    )
                )
            )
        )
        return result.scalar() or 0


# --- Plans ---

async def get_plans() -> list[Plan]:
    async with async_session() as session:
        result = await session.execute(
            select(Plan).where(Plan.is_active == True).order_by(Plan.sort_order)
        )
        return list(result.scalars().all())


async def get_plan(code: str) -> Plan | None:
    async with async_session() as session:
        result = await session.execute(select(Plan).where(Plan.code == code))
        return result.scalar_one_or_none()


async def create_plan(code: str, name: str, days: int, price: float, sort_order: int = 0) -> Plan:
    async with async_session() as session:
        plan = Plan(code=code, name=name, days=days, price=price, sort_order=sort_order)
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
        return plan


async def update_plan(plan_id: int, **kwargs) -> Plan | None:
    async with async_session() as session:
        await session.execute(update(Plan).where(Plan.id == plan_id).values(**kwargs))
        await session.commit()
        result = await session.execute(select(Plan).where(Plan.id == plan_id))
        return result.scalar_one_or_none()


async def delete_plan(plan_id: int):
    async with async_session() as session:
        await session.execute(delete(Plan).where(Plan.id == plan_id))
        await session.commit()


# --- Subscriptions ---

async def get_active_subscription(user_id: int) -> Subscription | None:
    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.is_active == True,
            ).order_by(Subscription.end_date.desc()).limit(5)
        )
        rows = list(result.scalars().all())
        now = datetime.now(timezone.utc)
        for sub in rows:
            end = sub.end_date
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end > now:
                return sub
        return None


async def get_subscriptions(user_id: int) -> list[Subscription]:
    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.created_at.desc(), Subscription.id.desc())
        )
        return list(result.scalars().all())


async def create_subscription(user_id: int, plan: str, end_date: datetime) -> Subscription:
    async with async_session() as session:
        sub = Subscription(user_id=user_id, plan=plan, end_date=end_date)
        session.add(sub)
        await session.commit()
        await session.refresh(sub)
        return sub


async def deactivate_expired_subscriptions():
    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.is_active == True)
        )
        now = datetime.now(timezone.utc)
        expired_ids = []
        for sub in result.scalars().all():
            end = sub.end_date
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            if end <= now:
                expired_ids.append(sub.id)
        if expired_ids:
            await session.execute(
                update(Subscription).where(Subscription.id.in_(expired_ids)).values(is_active=False)
            )
            await session.commit()


# --- Payments ---

async def create_payment(user_id: int, amount: float, provider: str, plan: str, description: str | None = None) -> Payment:
    async with async_session() as session:
        payment = Payment(
            user_id=user_id, amount=amount, provider=provider,
            plan=plan, description=description,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment


async def get_payment(payment_id) -> Payment | None:
    async with async_session() as session:
        result = await session.execute(select(Payment).where(Payment.id == payment_id))
        return result.scalar_one_or_none()


async def update_payment_status(payment_id, status: str, provider_payment_id: str | None = None) -> Payment | None:
    async with async_session() as session:
        values = {"status": status}
        if provider_payment_id:
            values["provider_payment_id"] = provider_payment_id
        if status == "completed":
            values["paid_at"] = datetime.now(timezone.utc)
        await session.execute(update(Payment).where(Payment.id == payment_id).values(**values))
        await session.commit()
        return await get_payment(payment_id)


async def get_all_payments(limit: int = 100) -> list[Payment]:
    async with async_session() as session:
        result = await session.execute(
            select(Payment).order_by(Payment.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def get_pending_payments() -> list[Payment]:
    async with async_session() as session:
        result = await session.execute(
            select(Payment).where(Payment.status == "pending").order_by(Payment.created_at.desc())
        )
        return list(result.scalars().all())


async def get_revenue() -> float:
    async with async_session() as session:
        result = await session.execute(
            select(func.sum(Payment.amount)).where(Payment.status == "completed")
        )
        return result.scalar() or 0.0


# --- Servers ---

async def get_servers() -> list[Server]:
    async with async_session() as session:
        result = await session.execute(
            select(Server).where(Server.is_active == True).order_by(Server.name)
        )
        return list(result.scalars().all())


async def get_all_servers() -> list[Server]:
    async with async_session() as session:
        result = await session.execute(select(Server).order_by(Server.created_at.desc()))
        return list(result.scalars().all())


async def get_server(server_id: int) -> Server | None:
    async with async_session() as session:
        result = await session.execute(select(Server).where(Server.id == server_id))
        return result.scalar_one_or_none()


async def create_server(name: str, host: str, port: int, protocol: str = "vless",
                        location: str | None = None, traffic_limit: float = 0,
                        is_active: bool = True) -> Server:
    async with async_session() as session:
        server = Server(name=name, host=host, port=port, protocol=protocol,
                        location=location, traffic_limit=traffic_limit,
                        is_active=is_active)
        session.add(server)
        await session.commit()
        await session.refresh(server)
        return server


async def update_server(server_id: int, **kwargs) -> Server | None:
    async with async_session() as session:
        await session.execute(update(Server).where(Server.id == server_id).values(**kwargs))
        await session.commit()
        return await get_server(server_id)


async def delete_server(server_id: int):
    async with async_session() as session:
        await session.execute(delete(Server).where(Server.id == server_id))
        await session.commit()


# --- VPN Configs ---

async def create_vpn_config(
    user_id: int, server_id: int, subscription_id: int | None,
    config_data: str, config_link: str, uuid: str, expires_at: datetime,
) -> VPNConfig:
    async with async_session() as session:
        vpn_config = VPNConfig(
            user_id=user_id, server_id=server_id, subscription_id=subscription_id,
            config_data=config_data, config_link=config_link, uuid=uuid,
            expires_at=expires_at,
        )
        session.add(vpn_config)
        await session.commit()
        await session.refresh(vpn_config)
        return vpn_config


async def get_active_configs(user_id: int) -> list[VPNConfig]:
    async with async_session() as session:
        result = await session.execute(
            select(VPNConfig).options(selectinload(VPNConfig.server)).where(
                VPNConfig.user_id == user_id,
                VPNConfig.is_active == True,
                VPNConfig.expires_at > datetime.now(timezone.utc),
            ).order_by(VPNConfig.created_at.desc())
        )
        return list(result.scalars().all())


async def get_all_active_configs() -> list[VPNConfig]:
    async with async_session() as session:
        result = await session.execute(
            select(VPNConfig).options(selectinload(VPNConfig.server)).where(
                VPNConfig.is_active == True,
                VPNConfig.expires_at > datetime.now(timezone.utc),
            ).order_by(VPNConfig.created_at.desc())
        )
        return list(result.scalars().all())


async def get_vpn_config(config_id: int) -> VPNConfig | None:
    async with async_session() as session:
        result = await session.execute(
            select(VPNConfig).options(
                selectinload(VPNConfig.server),
                selectinload(VPNConfig.user),
            ).where(VPNConfig.id == config_id)
        )
        return result.scalar_one_or_none()


async def deactivate_config(config_id: int):
    async with async_session() as session:
        await session.execute(
            update(VPNConfig).where(VPNConfig.id == config_id).values(is_active=False)
        )
        await session.commit()


async def get_or_create_user(telegram_id: int, **kwargs) -> User:
    user = await get_user(telegram_id)
    if not user:
        token = uuid.uuid4().hex[:32]
        user = await create_user(telegram_id, token=token, **kwargs)
    elif not user.token:
        token = uuid.uuid4().hex[:32]
        user = await update_user(telegram_id, token=token)
    return user
