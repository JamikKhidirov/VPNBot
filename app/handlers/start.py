from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from app.database import get_or_create_user
from app.keyboards.inline import main_menu_keyboard, plans_keyboard
from app.services.subscription import subscription_service

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer_animation(
        animation="https://i.imgur.com/Vn7YBYE.gif",
        caption="🔒 Привет! Секунду..."
    )

    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code or "ru",
    )

    status_data = await subscription_service.get_user_status(message.from_user.id)
    welcome_text = (
        f"👋 Привет, {message.from_user.first_name or 'пользователь'}!\n\n"
        "🔒 Этот бот предоставляет доступ к защищённому VPN-соединению.\n"
        "Твои данные в безопасности, а интернет без ограничений.\n\n"
    )

    if status_data["status"] == "active":
        welcome_text += (
            f"✅ Статус: <b>Активен</b>\n"
            f"⏳ Осталось дней: <b>{status_data['days_left']}</b>\n\n"
            f"Можешь продолжать пользоваться или продлить подписку."
        )
    else:
        welcome_text += (
            "🎁 <b>Попробуй бесплатно в течение 3 дней!</b>\n"
            "Просто выбери тариф ниже."
        )

    await message.answer(welcome_text, reply_markup=main_menu_keyboard(message.from_user.id), parse_mode="HTML")


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard(message.from_user.id))


@router.callback_query(F.data == "menu")
async def callback_menu(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu_keyboard(callback.from_user.id))
    await callback.answer()


@router.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    text = (
        "❓ <b>Помощь</b>\n\n"
        "1. <b>Как получить VPN?</b>\n"
        "   Нажми «Купить подписку» и выбери тариф.\n\n"
        "2. <b>Как импортировать конфиг?</b>\n"
        "   После покупки нажми «Мои конфиги», выбери нужный,\n"
        "   скопируй ссылку и импортируй в V2RayTun.\n\n"
        "3. <b>Пробный период</b>\n"
        "   Доступен 1 раз — 5 дней бесплатно.\n\n"
        "4. <b>Оплата</b>\n"
        "   Карты РФ, СБП, USDT через Crypto Bot.\n\n"
        "По вопросам: @admin_username"
    )
    await callback.message.edit_text(text, parse_mode="HTML",
                                     reply_markup=main_menu_keyboard(callback.from_user.id))
    await callback.answer()
