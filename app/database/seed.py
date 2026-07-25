from sqlalchemy import select, func

from app.database.engine import async_session
from app.database.models import Plan
from app.utils.pricing import DISCOUNT_INFO


DEFAULT_PLANS = [
    {
        "code": "trial",
        "name": "Пробный",
        "days": 3,
        "price": 0,
        "sort_order": 0,
    },
    {
        "code": "1month",
        "name": "1 месяц",
        "days": 30,
        "price": 70,
        "sort_order": 1,
    },
    {
        "code": "3months",
        "name": "3 месяца",
        "days": 90,
        "price": 189,
        "sort_order": 2,
    },
    {
        "code": "1year",
        "name": "1 год",
        "days": 365,
        "price": 588,
        "sort_order": 3,
    },
]


async def seed_plans():
    async with async_session() as session:
        result = await session.execute(select(func.count(Plan.id)))
        count = result.scalar()
        if count > 0:
            return False

        for plan_data in DEFAULT_PLANS:
            plan = Plan(**plan_data)
            session.add(plan)
        await session.commit()
        return True
