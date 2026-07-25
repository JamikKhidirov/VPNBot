from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.config import config


def main_menu_keyboard(user_id: int | None = None) -> InlineKeyboardMarkup:
    is_admin = user_id in config.ADMIN_IDS if user_id else False
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мой профиль", callback_data="profile")
    builder.button(text="🛒 Купить подписку", callback_data="buy")
    builder.button(text="🔗 Мои конфиги", callback_data="my_configs")
    builder.button(text="❓ Помощь", callback_data="help")
    if is_admin:
        builder.button(text="👑 Админ-панель", callback_data="admin")
    builder.adjust(1)
    return builder.as_markup()


def plans_keyboard(plans: list = None) -> InlineKeyboardMarkup:
    from app.utils.pricing import get_discount_text, get_plan_price_text

    builder = InlineKeyboardBuilder()
    if plans:
        for plan in plans:
            if plan.code == "trial":
                text = f"🎁 {plan.name} — Бесплатно"
            else:
                price = get_plan_price_text(plan.price)
                discount = get_discount_text(plan.code, plan.price)
                text = f"• {plan.name} — {price}{' 🔥' if discount else ''}"
            builder.button(text=text, callback_data=f"plan_{plan.code}")
    else:
        builder.button(text="🎁 Пробный 3 дня — Бесплатно", callback_data="plan_trial")
        builder.button(text="🌙 1 месяц — 70 ₽", callback_data="plan_1month")
        builder.button(text="🔥 3 месяца — 189 ₽ (скидка 10%)", callback_data="plan_3months")
        builder.button(text="🔥 1 год — 588 ₽ (скидка 30%)", callback_data="plan_1year")
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def payment_methods_keyboard(plan: str, providers: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if "yookassa" in providers:
        builder.button(text="💳 Карта / СБП (ЮKassa)", callback_data=f"pay_yookassa_{plan}")
    if "cryptobot" in providers:
        builder.button(text="₿ Crypto Bot (USDT)", callback_data=f"pay_cryptobot_{plan}")
    if "wallet" in providers:
        builder.button(text="🏦 Кошелёк (USDT/крипта)", callback_data=f"pay_wallet_{plan}")
    builder.button(text="◀ Назад", callback_data="buy")
    builder.adjust(1)
    return builder.as_markup()


def profile_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить конфиги", callback_data="refresh_configs")
    builder.button(text="🛒 Купить подписку", callback_data="buy")
    builder.button(text="◀ В меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀ В меню", callback_data="menu")
    return builder.as_markup()


def payment_url_keyboard(pay_url: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if pay_url:
        builder.button(text="💳 Оплатить", url=pay_url)
    builder.button(text="✅ Проверить оплату", callback_data="check_payment")
    builder.button(text="◀ Отмена", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def configs_keyboard(configs: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cfg in configs:
        label = f"🔗 {cfg.server.host if hasattr(cfg, 'server') and cfg.server else 'VPN'} (до {cfg.expires_at.strftime('%d.%m')})"
        builder.button(text=label, callback_data=f"config_{cfg.id}")
    builder.button(text="◀ Назад", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="💰 Доход", callback_data="admin_revenue")
    builder.button(text="💲 Тарифы", callback_data="admin_plans")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="🟢 Онлайн", callback_data="admin_online")
    builder.button(text="📊 Нагрузка", callback_data="admin_server_load")
    builder.button(text="➕ Добавить сервер", callback_data="admin_add_server")
    builder.button(text="📋 Список серверов", callback_data="admin_servers")
    builder.button(text="📥 Импорт с 3x-ui", callback_data="admin_import_inbounds")
    builder.button(text="🔗 Активные конфиги", callback_data="admin_configs")
    builder.button(text="🎁 Выдать VPN", callback_data="admin_give")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="◀ Главное меню", callback_data="menu")
    builder.adjust(2)
    return builder.as_markup()
