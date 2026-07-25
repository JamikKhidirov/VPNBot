import base64

from aiohttp import web

from app.database import get_user, get_active_configs


async def handle_subscription(request: web.Request) -> web.Response:
    token = request.match_info.get("token", "")

    if not token:
        return web.json_response({"error": "token required"}, status=400)

    # Ищем пользователя по токену
    from sqlalchemy import select
    from app.database.engine import async_session
    from app.database.models import User

    async with async_session() as session:
        result = await session.execute(select(User).where(User.token == token))
        user = result.scalar_one_or_none()

    if not user:
        return web.json_response({"error": "invalid token"}, status=404)

    if user.is_blocked:
        return web.json_response({"error": "user blocked"}, status=403)

    # Берём активные конфиги
    configs = await get_active_configs(user.id)
    if not configs:
        # Пустой список, возвращаем пустую подписку
        return web.Response(
            text=base64.b64encode(b"").decode(),
            content_type="text/plain; charset=utf-8",
            headers={"Subscription-Userinfo": "upload=0; download=0; total=0; expire=0"},
        )

    # Формируем список ссылок (по одной на строку)
    links = []
    total_traffic = 0
    max_expire = 0

    for cfg in configs:
        links.append(cfg.config_link)
        expire_ts = int(cfg.expires_at.timestamp())
        if expire_ts > max_expire:
            max_expire = expire_ts
        total_traffic += 200 * 1024**3  # 200GB per config

    # Формат V2RayTun: base64 encoded список ссылок (каждая с новой строки)
    encoded = base64.b64encode("\n".join(links).encode()).decode()

    user_info = (
        f"upload=0; download=0; "
        f"total={total_traffic}; "
        f"expire={max_expire}"
    )

    return web.Response(
        text=encoded,
        content_type="text/plain; charset=utf-8",
        headers={"Subscription-Userinfo": user_info},
    )


async def handle_sub_info(request: web.Request) -> web.Response:
    """Информация о подписке в JSON"""
    token = request.match_info.get("token", "")
    from sqlalchemy import select
    from app.database.engine import async_session
    from app.database.models import User

    async with async_session() as session:
        result = await session.execute(select(User).where(User.token == token))
        user = result.scalar_one_or_none()

    if not user:
        return web.json_response({"error": "invalid token"}, status=404)

    configs = await get_active_configs(user.id)
    return web.json_response({
        "status": "active",
        "configs": [
            {
                "link": c.config_link,
                "server": c.server.host if hasattr(c, "server") and c.server else "unknown",
                "expires": c.expires_at.isoformat(),
            }
            for c in configs
        ],
        "expires": max((c.expires_at for c in configs), default=None),
    })


def setup_subscription_routes(app: web.Application):
    app.router.add_get("/sub/{token}", handle_subscription)
    app.router.add_get("/sub/{token}/info", handle_sub_info)
    app.router.add_get("/", lambda r: web.Response(text="VPNBot Subscription Server"))
