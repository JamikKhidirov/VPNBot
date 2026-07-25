from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from app.database import get_user
from app.keyboards.inline import profile_keyboard, configs_keyboard, back_to_menu_keyboard
from app.services.subscription import subscription_service
from app.utils.helpers import format_date, format_days_left

router = Router()


@router.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery):
    status_data = await subscription_service.get_user_status(callback.from_user.id)
    if not status_data["exists"]:
        await callback.message.edit_text("Пользователь не найден.", reply_markup=back_to_menu_keyboard())
        await callback.answer()
        return

    user = status_data["user"]
    sub = status_data["active_subscription"]
    status_emojis = {"active": "✅", "inactive": "❌", "trial_expired": "⏳", "expired": "⏰"}

    text = (
        f"📋 <b>Мой профиль</b>\n\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"👤 Имя: {user.first_name or '—'}\n"
        f"📅 Регистрация: {format_date(user.created_at)}\n\n"
        f"<b>Статус подписки:</b> {status_emojis.get(status_data['status'], '❓')} {status_data['status'].upper()}\n"
    )

    if sub:
        text += (
            f"📌 Тариф: {sub.plan}\n"
            f"⏳ Осталось: {format_days_left(status_data['days_left'])}\n"
            f"📅 До: {format_date(sub.end_date)}\n"
        )
    else:
        text += "\n❌ Нет активной подписки."

    text += f"\n💰 Баланс: {user.balance:.2f} ₽"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "refresh_configs")
async def callback_refresh_configs(callback: CallbackQuery):
    status_data = await subscription_service.get_user_status(callback.from_user.id)
    if not status_data["configs"]:
        await callback.answer("Нет активных конфигов. Купи подписку!", show_alert=True)
        return
    await callback.message.edit_text(
        f"✅ Найдено активных конфигов: {len(status_data['configs'])}",
        reply_markup=configs_keyboard(status_data["configs"]),
    )
    await callback.answer()


@router.callback_query(F.data == "my_configs")
async def callback_my_configs(callback: CallbackQuery):
    status_data = await subscription_service.get_user_status(callback.from_user.id)
    if not status_data["configs"]:
        await callback.message.edit_text(
            "❌ У тебя нет активных конфигураций.\n"
            "Купи подписку, чтобы получить доступ к VPN.",
            reply_markup=back_to_menu_keyboard(),
        )
        await callback.answer()
        return

    text = "🔗 <b>Твои VPN-конфигурации:</b>\n\n"
    for i, cfg in enumerate(status_data["configs"], 1):
        text += (
            f"{i}. Сервер: {cfg.server.name if hasattr(cfg, 'server') and cfg.server else 'VPN'}\n"
            f"   📅 Истекает: {format_date(cfg.expires_at)}\n"
            f"   🔑 UUID: <code>{cfg.uuid[:12]}...</code>\n\n"
        )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=configs_keyboard(status_data["configs"]))
    await callback.answer()


@router.callback_query(F.data.startswith("config_"))
async def callback_show_config(callback: CallbackQuery):
    config_id = int(callback.data.split("_")[1])
    from app.database import get_vpn_config

    cfg = await get_vpn_config(config_id)
    if not cfg or not cfg.is_active:
        await callback.answer("Конфиг не найден или неактивен.", show_alert=True)
        return

    text = (
        f"🔗 <b>VPN конфигурация #{cfg.id}</b>\n\n"
        f"🌐 Сервер: {cfg.server.name if hasattr(cfg, 'server') and cfg.server else 'VPN'}\n"
        f"📅 Истекает: {format_date(cfg.expires_at)}\n"
        f"🔑 UUID: <code>{cfg.uuid}</code>\n\n"
        f"<b>Ссылка для импорта в V2RayTun:</b>\n"
        f"<code>{cfg.config_link}</code>\n\n"
        f"📱 Просто скопируй ссылку выше и импортируй её в приложение."
    )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_menu_keyboard())
    await callback.answer()
