import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.database import (
    init_db, close_db,
    get_user, get_user_by_id, create_user, update_user, get_or_create_user,
    get_all_users, get_users_count, get_active_users_count,
    get_plans, get_plan, create_plan, update_plan, delete_plan,
    get_active_subscription, get_subscriptions, create_subscription,
    deactivate_expired_subscriptions,
    create_payment, get_payment, update_payment_status,
    get_all_payments, get_pending_payments, get_revenue,
    get_servers, get_all_servers, get_server,
    create_server, update_server, delete_server,
    create_vpn_config, get_active_configs, get_all_active_configs,
    get_vpn_config, deactivate_config,
)
from app.config import config


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    from app.database.engine import engine
    from app.database.models import Base
    # Drop all rows and recreate tables
    async with engine.begin() as conn:
        for tbl in reversed(Base.metadata.sorted_tables):
            await conn.execute(tbl.delete())
    yield


async def get_or_create_plan(code, name, days, price):
    plan = await get_plan(code)
    if plan:
        return plan
    return await create_plan(code=code, name=name, days=days, price=price)


async def seed_test_data():
    user = await get_or_create_user(
        telegram_id=12345, username="testuser",
        first_name="Test", last_name="User", language_code="ru",
    )
    user2 = await get_or_create_user(
        telegram_id=67890, username="testuser2",
        first_name="Test2", last_name="User2", language_code="en",
    )
    plan = await get_or_create_plan(code="1month", name="1 месяц", days=30, price=299.0)
    plan_trial = await get_or_create_plan(code="trial", name="Пробный", days=5, price=0.0)
    server = await create_server(
        name="Test Server", host="95.123.45.67",
        port=443, protocol="vless", location="DE",
    )
    return {"user": user, "user2": user2, "plan": plan, "plan_trial": plan_trial, "server": server}


# ── User tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_user():
    u = await get_or_create_user(telegram_id=999, username="newguy")
    assert u.telegram_id == 999
    assert u.trial_used is False
    found = await get_user(999)
    assert found is not None
    assert found.id == u.id


@pytest.mark.asyncio
async def test_get_user_by_id():
    u = await get_or_create_user(telegram_id=111, username="byid")
    found = await get_user_by_id(u.id)
    assert found is not None
    assert found.telegram_id == 111


@pytest.mark.asyncio
async def test_update_user():
    u = await get_or_create_user(telegram_id=222, username="update_me")
    await update_user(222, first_name="Updated", trial_used=True)
    u2 = await get_user(222)
    assert u2.first_name == "Updated"
    assert u2.trial_used is True


@pytest.mark.asyncio
async def test_get_all_users_and_counts():
    await seed_test_data()
    users = await get_all_users()
    assert len(users) >= 2
    count = await get_users_count()
    assert count >= 2


@pytest.mark.asyncio
async def test_get_active_users_count():
    data = await seed_test_data()
    end = datetime.now(timezone.utc) + timedelta(days=30)
    await create_subscription(user_id=data["user"].id, plan="1month", end_date=end)
    active = await get_active_users_count()
    assert active >= 1


# ── Plan tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_plans():
    p = await create_plan(code="3months_test", name="3 месяца", days=90, price=699.0)
    assert p.code == "3months_test"
    plans = await get_plans()
    codes = [pl.code for pl in plans]
    assert "3months_test" in codes
    found = await get_plan("3months_test")
    assert found.price == 699.0


@pytest.mark.asyncio
async def test_update_plan():
    p = await create_plan(code="yearly_test", name="Год", days=365, price=1999.0)
    await update_plan(p.id, price=1499.0)
    updated = await get_plan("yearly_test")
    assert updated.price == 1499.0


@pytest.mark.asyncio
async def test_delete_plan():
    p = await create_plan(code="temp_test", name="Временный", days=1, price=1.0)
    await delete_plan(p.id)
    assert await get_plan("temp_test") is None


# ── Subscription tests ────────────────────────────────

@pytest.mark.asyncio
async def test_create_subscription():
    data = await seed_test_data()
    end = datetime.now(timezone.utc) + timedelta(days=30)
    sub = await create_subscription(user_id=data["user"].id, plan="1month", end_date=end)
    assert sub.id is not None
    assert sub.plan == "1month"
    assert sub.is_active is True


@pytest.mark.asyncio
async def test_get_active_subscription():
    data = await seed_test_data()
    old = datetime.now(timezone.utc) - timedelta(days=1)
    await create_subscription(user_id=data["user"].id, plan="trial", end_date=old)
    active = datetime.now(timezone.utc) + timedelta(days=30)
    sub2 = await create_subscription(user_id=data["user"].id, plan="1month", end_date=active)
    found = await get_active_subscription(data["user"].id)
    assert found is not None
    assert found.id == sub2.id


@pytest.mark.asyncio
async def test_get_subscriptions_ordered():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    s1 = await create_subscription(user_id=data["user"].id, plan="trial", end_date=now + timedelta(days=5))
    s2 = await create_subscription(user_id=data["user"].id, plan="1month", end_date=now + timedelta(days=30))
    subs = await get_subscriptions(data["user"].id)
    assert len(subs) >= 2
    # DESC по created_at — s2 создан позже, должен быть первым
    assert subs[0].id == s2.id


@pytest.mark.asyncio
async def test_deactivate_expired_subscriptions():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    sub_expired = await create_subscription(
        user_id=data["user"].id, plan="trial",
        end_date=now - timedelta(days=1),
    )
    sub_active = await create_subscription(
        user_id=data["user2"].id, plan="1month",
        end_date=now + timedelta(days=30),
    )
    await deactivate_expired_subscriptions()
    # Проверяем напрямую статус в БД
    from app.database.models import Subscription
    from app.database.engine import async_session
    from sqlalchemy import select
    async with async_session() as session:
        s1 = await session.get(Subscription, sub_expired.id)
        s2 = await session.get(Subscription, sub_active.id)
        assert s1.is_active is False
        assert s2.is_active is True


@pytest.mark.asyncio
async def test_get_revenue():
    data = await seed_test_data()
    p1 = await create_payment(user_id=data["user"].id, amount=299, provider="yookassa", plan="1month")
    await update_payment_status(p1.id, "completed")
    p2 = await create_payment(user_id=data["user2"].id, amount=699, provider="yookassa", plan="3months")
    await update_payment_status(p2.id, "completed")
    rev = await get_revenue()
    assert rev > 0
    assert rev == 299.0 + 699.0


# ── Server tests ──────────────────────────────────────

@pytest.mark.asyncio
async def test_create_get_servers():
    s = await create_server(name="Moscow", host="10.0.0.1", port=443, protocol="vless", location="RU")
    assert s.id is not None
    found = await get_server(s.id)
    assert found.name == "Moscow"
    all_s = await get_all_servers()
    assert len(all_s) >= 1
    active = await get_servers()
    assert len(active) >= 1


@pytest.mark.asyncio
async def test_update_server():
    s = await create_server(name="Test", host="1.2.3.4", port=443)
    await update_server(s.id, port=8443, is_active=False)
    updated = await get_server(s.id)
    assert updated.port == 8443
    assert updated.is_active is False


@pytest.mark.asyncio
async def test_delete_server():
    s = await create_server(name="DelMe", host="9.9.9.9", port=443)
    await delete_server(s.id)
    assert await get_server(s.id) is None


@pytest.mark.asyncio
async def test_get_servers_only_active():
    s1 = await create_server(name="Active1", host="1.1.1.1", port=443, is_active=True)
    s2 = await create_server(name="Inactive", host="2.2.2.2", port=443, is_active=False)
    active = await get_servers()
    assert len(active) >= 1
    for s in active:
        assert s.is_active is True


# ── VPN Config tests ─────────────────────────────────

@pytest.mark.asyncio
async def test_create_vpn_config():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    cfg = await create_vpn_config(
        user_id=data["user"].id, server_id=data["server"].id, subscription_id=None,
        config_data='{"link": "vless://..."}', config_link="vless://test@host:443?key=val#VPN",
        uuid=str(uuid.uuid4()), expires_at=now + timedelta(days=30),
    )
    assert cfg.id is not None
    assert cfg.is_active is True


@pytest.mark.asyncio
async def test_get_active_configs():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    cfg1 = await create_vpn_config(
        user_id=data["user"].id, server_id=data["server"].id, subscription_id=None,
        config_data="{}", config_link="vless://a",
        uuid=str(uuid.uuid4()), expires_at=now + timedelta(days=30),
    )
    cfg2 = await create_vpn_config(
        user_id=data["user"].id, server_id=data["server"].id, subscription_id=None,
        config_data="{}", config_link="vless://b",
        uuid=str(uuid.uuid4()), expires_at=now - timedelta(days=1),
    )
    active = await get_active_configs(data["user"].id)
    uuids = [c.uuid for c in active]
    assert cfg1.uuid in uuids
    assert cfg2.uuid not in uuids


@pytest.mark.asyncio
async def test_get_all_active_configs():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    await create_vpn_config(
        user_id=data["user"].id, server_id=data["server"].id, subscription_id=None,
        config_data="{}", config_link="vless://c",
        uuid=str(uuid.uuid4()), expires_at=now + timedelta(days=30),
    )
    all_active = await get_all_active_configs()
    assert len(all_active) >= 1


@pytest.mark.asyncio
async def test_get_vpn_config_with_server():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    cfg = await create_vpn_config(
        user_id=data["user"].id, server_id=data["server"].id, subscription_id=None,
        config_data="{}", config_link="vless://d",
        uuid=str(uuid.uuid4()), expires_at=now + timedelta(days=30),
    )
    found = await get_vpn_config(cfg.id)
    assert found.server is not None
    assert found.server.host == "95.123.45.67"


@pytest.mark.asyncio
async def test_deactivate_config():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    cfg = await create_vpn_config(
        user_id=data["user"].id, server_id=data["server"].id, subscription_id=None,
        config_data="{}", config_link="vless://e",
        uuid=str(uuid.uuid4()), expires_at=now + timedelta(days=30),
    )
    await deactivate_config(cfg.id)
    updated = await get_vpn_config(cfg.id)
    assert updated.is_active is False


# ── V2Ray service tests ──────────────────────────────

@pytest.mark.asyncio
async def test_generate_uuid():
    from app.services.v2ray import v2ray_service
    uid = v2ray_service.generate_uuid()
    assert len(uid) == 36
    assert uid.count("-") == 4


@pytest.mark.asyncio
async def test_generate_vless_link():
    from app.services.v2ray import v2ray_service
    link = v2ray_service.generate_link(
        host="95.123.45.67", port=443,
        uid="550e8400-e29b-41d4-a716-446655440000",
        protocol="vless",
    )
    assert link.startswith("vless://")
    assert "95.123.45.67" in link


@pytest.mark.asyncio
async def test_generate_vmess_link():
    from app.services.v2ray import v2ray_service
    link = v2ray_service.generate_link(
        host="95.123.45.67", port=443,
        uid="550e8400-e29b-41d4-a716-446655440000",
        protocol="vmess",
    )
    assert link.startswith("vmess://")


@pytest.mark.asyncio
async def test_parse_inbound():
    from app.services.v2ray import v2ray_service
    inbound = {"port": 443, "protocol": "vless", "remark": "Main", "settings": '{"clients": []}'}
    parsed = await v2ray_service.parse_inbound(inbound, "95.123.45.67")
    assert parsed["host"] == "95.123.45.67"
    assert parsed["port"] == 443
    assert parsed["name"] == "Main"


# ── SubscriptionService tests ─────────────────────────

@pytest.mark.asyncio
async def test_get_user_status_inactive():
    data = await seed_test_data()
    from app.services.subscription import subscription_service
    status = await subscription_service.get_user_status(12345)
    assert status["exists"] is True
    # Без подписки статус должен быть не active
    assert status["status"] in ("inactive", "expired")


@pytest.mark.asyncio
async def test_get_user_status_active():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    await create_subscription(user_id=data["user"].id, plan="1month", end_date=now + timedelta(days=30))
    from app.services.subscription import subscription_service
    status = await subscription_service.get_user_status(12345)
    assert status["status"] == "active"
    assert status["days_left"] > 0


@pytest.mark.asyncio
async def test_activate_trial_no_server():
    from app.services.subscription import subscription_service
    result = await subscription_service.activate_trial(12345)
    assert result["success"] is False


@pytest.mark.asyncio
async def test_activate_trial_success():
    data = await seed_test_data()
    from app.services.subscription import subscription_service
    result = await subscription_service.activate_trial(12345)
    assert result["success"] is True
    assert result["subscription"].plan == "trial"
    user = await get_user(12345)
    assert user.trial_used is True


@pytest.mark.asyncio
async def test_activate_trial_already_used():
    data = await seed_test_data()
    await update_user(12345, trial_used=True)
    from app.services.subscription import subscription_service
    result = await subscription_service.activate_trial(12345)
    assert result["success"] is False


# ── create_user_config ───────────────────────────────

@pytest.mark.asyncio
async def test_create_user_config():
    data = await seed_test_data()
    from app.services.v2ray import v2ray_service
    result = await v2ray_service.create_user_config(
        user_id=data["user"].id, server_id=data["server"].id,
        duration_days=30, server_host=data["server"].host, server_port=data["server"].port,
    )
    assert result["link"].startswith("vless://")
    assert result["host"] == "95.123.45.67"


# ── Server relationships ─────────────────────────────

@pytest.mark.asyncio
async def test_server_relationships():
    data = await seed_test_data()
    now = datetime.now(timezone.utc)
    cfg = await create_vpn_config(
        user_id=data["user"].id, server_id=data["server"].id, subscription_id=None,
        config_data="{}", config_link="vless://rel_test",
        uuid=str(uuid.uuid4()), expires_at=now + timedelta(days=30),
    )
    found = await get_vpn_config(cfg.id)
    assert found.server is not None
    assert found.server.name == "Test Server"
    assert found.user is not None
    assert found.user.telegram_id == 12345
