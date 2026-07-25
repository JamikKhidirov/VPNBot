import uuid
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.config import config
from app.database import (
    get_user, get_all_users, get_all_servers, get_server, get_plans,
    get_revenue, get_users_count, get_active_users_count, get_all_payments,
    get_all_active_configs, get_active_configs, get_active_subscription, get_subscriptions,
    create_server, update_server, delete_server,
    create_plan, update_plan, delete_plan, create_subscription,
    update_user, get_or_create_user, get_plan,
    get_pending_payments, get_payment, get_user_by_id,
)
from app.keyboards.inline import admin_keyboard, main_menu_keyboard, back_to_menu_keyboard
from app.services.v2ray import v2ray_service
from app.services.subscription import subscription_service

logger = logging.getLogger(__name__)

router = Router()


# --- FSM States ---

class AdminStates(StatesGroup):
    broadcast_text = State()
    add_server_name = State()
    add_server_host = State()
    add_server_port = State()
    add_server_protocol = State()
    add_server_location = State()
    edit_server_field = State()
    add_plan_code = State()
    add_plan_name = State()
    add_plan_days = State()
    add_plan_price = State()
    edit_plan_field = State()
    give_user_id = State()
    import_host = State()
    give_plan = State()
    give_duration = State()
    vps_add_ip = State()
    vps_add_password = State()
    vps_add_location = State()
    vps_add_name = State()


# --- Admin check ---

def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def ensure_admin(message: Message | CallbackQuery) -> bool:
    user_id = message.from_user.id
    if not is_admin(user_id):
        if isinstance(message, Message):
            await message.answer("⛔ У вас нет прав администратора.")
        else:
            await message.answer("⛔ У вас нет прав администратора.", show_alert=True)
        return False
    return True


# --- Admin commands ---

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await ensure_admin(message):
        return
    text = (
        "👑 <b>Админ-панель</b>\n\n"
        "Выбери действие:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin")
async def callback_admin(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    text = "👑 <b>Админ-панель</b>\n\nВыбери действие:"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await callback.answer()


# --- STATISTICS ---

@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    users_count = await get_users_count()
    active_users = await get_active_users_count()
    revenue = await get_revenue()
    active_configs = await get_all_active_configs()
    payments = await get_all_payments(10)

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{users_count}</b>\n"
        f"✅ Активных подписок: <b>{active_users}</b>\n"
        f"🔗 Активных конфигов: <b>{len(active_configs)}</b>\n"
        f"💰 Общий доход: <b>{revenue:.2f} ₽</b>\n\n"
        f"<b>Последние платежи:</b>\n"
    )

    for p in payments[:5]:
        text += f"• {p.amount:.0f}₽ — {p.status} — {p.created_at.strftime('%d.%m %H:%M')}\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await callback.answer()


# --- SERVER MANAGEMENT ---

@router.callback_query(F.data == "admin_servers")
async def callback_admin_servers(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    servers = await get_all_servers()

    text = "📋 <b>Список серверов:</b>\n\n"
    if not servers:
        text += "Нет добавленных серверов."
    else:
        for s in servers:
            status_emoji = "✅" if s.is_active else "⛔"
            text += (
                f"{status_emoji} <b>{s.name}</b> ({s.location or '?'})\n"
                f"   {s.host}:{s.port} | {s.protocol}\n"
                f"   ID: {s.id}\n\n"
            )

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить сервер", callback_data="admin_add_server")
    builder.button(text="◀ Назад", callback_data="admin")
    builder.adjust(1)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "admin_add_server")
async def callback_admin_add_server(callback: CallbackQuery, state: FSMContext):
    if not await ensure_admin(callback):
        return
    await state.set_state(AdminStates.add_server_name)
    await callback.message.edit_text(
        "➕ <b>Добавление сервера</b>\n\n"
        "Введи <b>название сервера</b> (например: NL-1, DE-Frankfurt):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.add_server_name)
async def admin_add_server_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminStates.add_server_host)
    await message.answer("Введи <b>хост/IP сервера</b>:", parse_mode="HTML")


@router.message(AdminStates.add_server_host)
async def admin_add_server_host(message: Message, state: FSMContext):
    await state.update_data(host=message.text.strip())
    await state.set_state(AdminStates.add_server_port)
    await message.answer("Введи <b>порт</b> (по умолчанию 443):", parse_mode="HTML")


@router.message(AdminStates.add_server_port)
async def admin_add_server_port(message: Message, state: FSMContext):
    try:
        port = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Порт должен быть числом. Попробуй ещё раз:")
        return
    await state.update_data(port=port)
    await state.set_state(AdminStates.add_server_protocol)
    await message.answer(
        "Введи <b>протокол</b> (vless / vmess / shadowsocks):\n"
        "По умолчанию: vless",
        parse_mode="HTML",
    )


@router.message(AdminStates.add_server_protocol)
async def admin_add_server_protocol(message: Message, state: FSMContext):
    protocol = message.text.strip().lower()
    if protocol not in ("vless", "vmess", "shadowsocks"):
        protocol = "vless"
    await state.update_data(protocol=protocol)
    await state.set_state(AdminStates.add_server_location)
    await message.answer("Введи <b>локацию</b> сервера (например: Netherlands):", parse_mode="HTML")


@router.message(AdminStates.add_server_location)
async def admin_add_server_location(message: Message, state: FSMContext):
    data = await state.update_data(location=message.text.strip())
    server = await create_server(
        name=data["name"], host=data["host"], port=data["port"],
        protocol=data.get("protocol", "vless"), location=data["location"],
    )
    await state.clear()
    text = (
        f"✅ <b>Сервер добавлен!</b>\n\n"
        f"Название: {server.name}\n"
        f"Хост: {server.host}:{server.port}\n"
        f"Протокол: {server.protocol}\n"
        f"Локация: {server.location or '—'}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


# --- PLAN MANAGEMENT ---

@router.callback_query(F.data == "admin_plans")
async def callback_admin_plans(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    plans = await get_plans()

    text = "💲 <b>Управление тарифами:</b>\n\n"
    for p in plans:
        price_str = f"{int(p.price)}₽" if p.price == int(p.price) else f"{p.price}₽"
        text += (
            f"• <b>{p.name}</b> ({p.code})\n"
            f"  {p.days} дн. | {price_str} | сортировка: {p.sort_order}\n"
            f"  ID: {p.id}\n\n"
        )

    text += "Чтобы изменить, используй команды:\n"
    text += "/add_plan — добавить тариф\n"
    text += "/edit_plan [id] — изменить тариф\n"
    text += "/del_plan [id] — удалить тариф"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await callback.answer()


@router.message(Command("add_plan"))
async def cmd_add_plan(message: Message, state: FSMContext):
    if not await ensure_admin(message):
        return
    await state.set_state(AdminStates.add_plan_code)
    await message.answer(
        "➕ <b>Добавление тарифа</b>\n\n"
        "Введи <b>код тарифа</b> (латиница, например: 1month, trial):",
        parse_mode="HTML",
    )


@router.message(AdminStates.add_plan_code)
async def admin_add_plan_code(message: Message, state: FSMContext):
    code = message.text.strip().lower().replace(" ", "_")
    existing = await get_plan(code)
    if existing:
        await message.answer("❌ Такой код уже существует. Введи другой:")
        return
    await state.update_data(code=code)
    await state.set_state(AdminStates.add_plan_name)
    await message.answer("Введи <b>название</b> тарифа (например: 1 месяц):", parse_mode="HTML")


@router.message(AdminStates.add_plan_name)
async def admin_add_plan_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminStates.add_plan_days)
    await message.answer("Введи <b>количество дней</b> действия:", parse_mode="HTML")


@router.message(AdminStates.add_plan_days)
async def admin_add_plan_days(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Должно быть число. Попробуй ещё раз:")
        return
    await state.update_data(days=days)
    await state.set_state(AdminStates.add_plan_price)
    await message.answer(
        "Введи <b>цену</b> в рублях (0 — если бесплатный):",
        parse_mode="HTML",
    )


@router.message(AdminStates.add_plan_price)
async def admin_add_plan_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Должно быть число. Попробуй ещё раз:")
        return
    data = await state.update_data(price=price)
    plan = await create_plan(
        code=data["code"], name=data["name"],
        days=data["days"], price=data["price"],
        sort_order=data["days"],
    )
    await state.clear()
    price_str = f"{int(plan.price)}₽" if plan.price == int(plan.price) else f"{plan.price}₽"
    await message.answer(
        f"✅ <b>Тариф добавлен!</b>\n\n"
        f"Код: {plan.code}\n"
        f"Название: {plan.name}\n"
        f"Дней: {plan.days} | Цена: {price_str}",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


@router.message(Command("edit_plan"))
async def cmd_edit_plan(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /edit_plan [id] [поле] [значение]\n"
                             "Поля: name, days, price, sort_order, is_active\n"
                             "Пример: /edit_plan 2 price 499")
        return
    try:
        parts = args[1].split(maxsplit=2)
        plan_id = int(parts[0])
        field = parts[1]
        value = parts[2]
    except (IndexError, ValueError):
        await message.answer("❌ Неверный формат. Используй: /edit_plan [id] [поле] [значение]")
        return

    if field == "price":
        value = float(value.replace(",", "."))
    elif field == "days":
        value = int(value)
    elif field == "sort_order":
        value = int(value)
    elif field == "is_active":
        value = value.lower() in ("true", "1", "да", "yes")

    plan = await update_plan(plan_id, **{field: value})
    if plan:
        await message.answer(f"✅ Тариф #{plan_id} обновлён: {field} = {value}")
    else:
        await message.answer("❌ Тариф не найден.")


@router.message(Command("del_plan"))
async def cmd_del_plan(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /del_plan [id]")
        return
    try:
        plan_id = int(args[1])
        await delete_plan(plan_id)
        await message.answer(f"✅ Тариф #{plan_id} удалён.")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")


# --- USER MANAGEMENT ---

@router.message(Command("give"))
async def cmd_give_vpn(message: Message, state: FSMContext):
    """Выдать VPN пользователю: /give @username 1month"""
    if not await ensure_admin(message):
        return
    await state.set_state(AdminStates.give_user_id)
    await message.answer(
        "🎁 <b>Выдача VPN пользователю</b>\n\n"
        "Введи <b>Telegram ID</b> или @username пользователя:",
        parse_mode="HTML",
    )


@router.message(AdminStates.give_user_id)
async def admin_give_user_id(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith("@"):
        users = await get_all_users()
        target = next((u for u in users if u.username and u.username.lower() == text.lower().lstrip("@")), None)
        if not target:
            await message.answer("❌ Пользователь не найден в базе.")
            return
    else:
        try:
            tid = int(text)
            target = await get_user(tid)
            if not target:
                await message.answer("❌ Пользователь с таким ID не найден в базе.")
                return
        except ValueError:
            await message.answer("❌ Неверный формат. Введи Telegram ID или @username:")
            return

    await state.update_data(target_id=target.telegram_id)
    await state.set_state(AdminStates.give_plan)
    plans = await get_plans()
    text = "Выбери <b>тариф</b> (введи код):\n\n"
    for p in plans:
        text += f"• <code>{p.code}</code> — {p.name} ({p.days} дн.)\n"
    await message.answer(text, parse_mode="HTML")


@router.message(AdminStates.give_plan)
async def admin_give_plan(message: Message, state: FSMContext):
    plan_code = message.text.strip().lower()
    plan = await get_plan(plan_code)
    if not plan:
        await message.answer("❌ Такого тарифа нет. Введи код из списка:")
        return
    await state.update_data(plan_code=plan_code)
    await state.set_state(AdminStates.give_duration)
    await message.answer(
        f"Сколько <b>дней</b> выдать? (по умолчанию {plan.days}):",
        parse_mode="HTML",
    )


@router.message(AdminStates.give_duration)
async def admin_give_duration(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        days = int(message.text.strip())
    except ValueError:
        days = None

    if not days:
        plan = await get_plan(data["plan_code"])
        days = plan.days if plan else 30

    target_id = data["target_id"]
    target = await get_user(target_id)
    if not target:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return

    end_date = datetime.now(timezone.utc) + timedelta(days=days)
    sub = await create_subscription(user_id=target.id, plan=data["plan_code"], end_date=end_date)

    servers = await get_all_servers()
    active_servers = [s for s in servers if s.is_active]
    config_result = None
    if active_servers:
        config_result = await v2ray_service.create_user_config(
            user_id=target.id, server_id=active_servers[0].id,
            subscription_id=sub.id, duration_days=days,
        )

    await state.clear()
    text = (
        f"✅ <b>VPN выдан!</b>\n\n"
        f"👤 Пользователь: <code>{target_id}</code> (@{target.username or '—'})\n"
        f"🗓 Тариф: {data['plan_code']}\n"
        f"📅 Дней: {days}\n"
        f"📆 До: {end_date.strftime('%d.%m.%Y')}\n"
    )
    if config_result:
        text += f"\n🔗 Ссылка: <code>{config_result['link']}</code>"

    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(Command("ban"))
async def cmd_ban_user(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /ban [telegram_id]")
        return
    try:
        tid = int(args[1])
        user = await update_user(tid, is_blocked=True)
        if user:
            await message.answer(f"✅ Пользователь {tid} заблокирован.")
        else:
            await message.answer("❌ Пользователь не найден.")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")


@router.message(Command("unban"))
async def cmd_unban_user(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /unban [telegram_id]")
        return
    try:
        tid = int(args[1])
        user = await update_user(tid, is_blocked=False)
        if user:
            await message.answer(f"✅ Пользователь {tid} разблокирован.")
        else:
            await message.answer("❌ Пользователь не найден.")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")


# --- BROADCAST ---

@router.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not await ensure_admin(callback):
        return
    await state.set_state(AdminStates.broadcast_text)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Отправь текст для рассылки всем пользователям.\n"
        "Поддерживается HTML-разметка.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.broadcast_text)
async def admin_broadcast_text(message: Message, state: FSMContext):
    users = await get_all_users()
    sent = 0
    blocked = 0
    for u in users:
        if u.is_blocked:
            blocked += 1
            continue
        try:
            await message.bot.send_message(
                u.telegram_id,
                f"📢 <b>Сообщение от администрации:</b>\n\n{message.text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            blocked += 1

    await state.clear()
    await message.answer(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Отправлено: {sent}\n"
        f"Не доставлено: {blocked}\n"
        f"Всего: {len(users)}",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


# --- CONFIGS MANAGEMENT ---

@router.message(Command("configs"))
async def cmd_list_configs(message: Message):
    if not await ensure_admin(message):
        return
    configs = await get_all_active_configs()
    text = f"🔗 <b>Активные конфиги:</b> {len(configs)}\n\n"
    for cfg in configs[:20]:
        user_info = f"UID:{cfg.user_id}"
        text += f"• {cfg.uuid[:12]}... | expires: {cfg.expires_at.strftime('%d.%m')} | {user_info}\n"

    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


# --- STATS COMMAND ---

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not await ensure_admin(message):
        return
    users_count = await get_users_count()
    active_users = await get_active_users_count()
    revenue = await get_revenue()
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"Пользователей: {users_count}\n"
        f"Активных: {active_users}\n"
        f"Доход: {revenue:.2f} ₽",
        parse_mode="HTML",
    )


# --- REVENUE ---

@router.callback_query(F.data == "admin_revenue")
async def callback_admin_revenue(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    revenue = await get_revenue()
    payments = await get_all_payments(50)
    completed = [p for p in payments if p.status == "completed"]
    total_payments = len(payments)
    total_completed = len(completed)

    text = (
        f"💰 <b>Финансы</b>\n\n"
        f"💵 Общий доход: <b>{revenue:.2f} ₽</b>\n"
        f"📊 Всего платежей: {total_payments}\n"
        f"✅ Успешных: {total_completed}\n"
        f"❌ Отменено/Ошибок: {total_payments - total_completed}\n\n"
        f"<b>Последние 10 платежей:</b>\n"
    )
    for p in payments[:10]:
        emoji = "✅" if p.status == "completed" else "⏳" if p.status == "pending" else "❌"
        text += f"{emoji} {p.amount:.0f}₽ · {p.plan} · {p.created_at.strftime('%d.%m %H:%M')}\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await callback.answer()


# --- USERS LIST ---

@router.callback_query(F.data == "admin_users")
async def callback_admin_users(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    users = await get_all_users()
    active_count = await get_active_users_count()

    text = (
        f"👥 <b>Пользователи:</b> {len(users)}\n"
        f"✅ Активных подписок: {active_count}\n\n"
    )
    for u in users[:15]:
        status_emoji = "🚫" if u.is_blocked else "✅"
        name = u.first_name or u.username or f"ID{u.telegram_id}"
        text += f"• {status_emoji} {name} | ID: <code>{u.telegram_id}</code>\n"
        if u.trial_used:
            text += "  🎁 Триал: да\n"
    if len(users) > 15:
        text += f"\n...и ещё {len(users) - 15} пользователей"

    text += "\n\n🔍 Найти пользователя: /find telegram_id"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await callback.answer()


@router.message(Command("find"))
async def cmd_find_user(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /find [telegram_id или @username]")
        return
    query = args[1].strip()
    users = await get_all_users()
    target = None
    if query.startswith("@"):
        target = next((u for u in users if u.username and u.username.lower() == query.lower().lstrip("@")), None)
    else:
        try:
            tid = int(query)
            target = await get_user(tid)
        except ValueError:
            target = next((u for u in users if u.first_name and query.lower() in u.first_name.lower()), None)

    if not target:
        await message.answer("❌ Пользователь не найден")
        return

    active_sub = await get_active_subscription(target.id)
    configs = await get_active_configs(target.id) if active_sub else []

    text = (
        f"👤 <b>Пользователь</b>\n\n"
        f"🆔 ID: <code>{target.telegram_id}</code>\n"
        f"👤 Имя: {target.first_name or '—'}\n"
        f"📛 Username: @{target.username or '—'}\n"
        f"🚫 Заблокирован: {'Да' if target.is_blocked else 'Нет'}\n"
        f"🎁 Триал: {'Использован' if target.trial_used else 'Не использован'}\n"
        f"🗓 Регистрация: {target.created_at.strftime('%d.%m.%Y')}\n"
    )
    if active_sub:
        text += f"✅ Подписка активна до {active_sub.end_date.strftime('%d.%m.%Y')}\n"
        text += f"🔗 Конфигов: {len(configs)}\n"
    else:
        text += "❌ Нет активной подписки\n"

    text += f"\nКоманды:\n/ban {target.telegram_id}\n/unban {target.telegram_id}"
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


# --- CONFIGS ---

@router.callback_query(F.data == "admin_configs")
async def callback_admin_configs(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    configs = await get_all_active_configs()
    text = f"🔗 <b>Активные конфиги:</b> {len(configs)}\n\n"
    for cfg in configs[:20]:
        text += f"• UUID: <code>{cfg.uuid[:16]}...</code> | "
        text += f"Истекает: {cfg.expires_at.strftime('%d.%m')}\n"
    if len(configs) > 20:
        text += f"\n...и ещё {len(configs) - 20} конфигов"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await callback.answer()


# --- GIVE VPN VIA BUTTON ---

@router.callback_query(F.data == "admin_give")
async def callback_admin_give(callback: CallbackQuery, state: FSMContext):
    if not await ensure_admin(callback):
        return
    await state.set_state(AdminStates.give_user_id)
    await callback.message.edit_text(
        "🎁 <b>Выдача VPN пользователю</b>\n\n"
        "Введи <b>Telegram ID</b> или @username пользователя:",
        parse_mode="HTML",
    )
    await callback.answer()


# --- SERVER DETAIL ---

@router.message(Command("server"))
async def cmd_server_detail(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /server [id]")
        return
    try:
        srv = await get_server(int(args[1]))
    except ValueError:
        await message.answer("❌ ID должен быть числом")
        return
    if not srv:
        await message.answer("❌ Сервер не найден")
        return

    configs = await get_all_active_configs()
    server_configs = [c for c in configs if c.server_id == srv.id]
    users_on_server = len(set(c.user_id for c in server_configs))

    text = (
        f"🌐 <b>Сервер: {srv.name}</b>\n\n"
        f"📍 Локация: {srv.location or '—'}\n"
        f"🔗 Хост: <code>{srv.host}</code>\n"
        f"🔌 Порт: {srv.port}\n"
        f"📡 Протокол: {srv.protocol}\n"
        f"✅ Статус: {'Активен' if srv.is_active else 'Отключён'}\n"
        f"👥 Пользователей: {users_on_server}\n"
        f"🔗 Конфигов: {len(server_configs)}\n"
        f"📊 Трафик: {srv.traffic_used:.1f} GB / {srv.traffic_limit:.1f} GB\n"
        f"🆔 ID: {srv.id}\n\n"
        f"Команды:\n"
        f"  /server_toggle {srv.id} — вкл/выкл сервер\n"
        f"  /server_del {srv.id} — удалить сервер"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(Command("server_toggle"))
async def cmd_server_toggle(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /server_toggle [id]")
        return
    try:
        srv = await get_server(int(args[1]))
        if not srv:
            await message.answer("❌ Сервер не найден")
            return
        await update_server(srv.id, is_active=not srv.is_active)
        new_status = "включён" if not srv.is_active else "отключён"
        await message.answer(f"✅ Сервер #{srv.id} ({srv.name}) {new_status}")
    except ValueError:
        await message.answer("❌ ID должен быть числом")


@router.message(Command("server_del"))
async def cmd_server_del(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /server_del [id]")
        return
    try:
        srv = await get_server(int(args[1]))
        if not srv:
            await message.answer("❌ Сервер не найден")
            return
        await delete_server(srv.id)
        await message.answer(f"✅ Сервер #{srv.id} ({srv.name}) удалён")
    except ValueError:
        await message.answer("❌ ID должен быть числом")


# --- CHECK SERVER ---

@router.message(Command("check_server"))
async def cmd_check_server(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /check_server [id]")
        return
    try:
        srv = await get_server(int(args[1]))
        if not srv:
            await message.answer("❌ Сервер не найден")
            return
    except ValueError:
        await message.answer("❌ ID должен быть числом")
        return

    msg = await message.answer(f"🔍 Проверяю сервер #{srv.id} ({srv.host})...")
    health = await v2ray_service.check_server_health(srv.host)

    if health["alive"]:
        text = (
            f"✅ <b>Сервер #{srv.id} ({srv.name}) — ONLINE</b>\n\n"
            f"📍 {srv.host}:{srv.port} ({srv.location or '?'})\n"
            f"📡 3x-ui: доступен\n"
            f"📦 Инбаундов: {health['inbounds']}\n"
            f"👤 Всего клиентов: {health['clients']}"
        )
    else:
        text = (
            f"❌ <b>Сервер #{srv.id} ({srv.name}) — OFFLINE</b>\n\n"
            f"📍 {srv.host}:{srv.port}\n"
            f"📡 3x-ui: НЕ доступен\n"
            f"⚠️ {health.get('error', 'Нет ответа от API')}\n\n"
            f"Проверь:\n"
            f"• Запущен ли 3x-ui на сервере\n"
            f"• Доступен ли порт 2053\n"
            f"• Правильные ли логин/пароль в .env (V2RAY_USER, V2RAY_PASS)"
        )

    await msg.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


# --- IMPORT INBOUNDS FROM 3x-UI ---

@router.callback_query(F.data == "admin_import_inbounds")
async def callback_admin_import_inbounds(callback: CallbackQuery, state: FSMContext):
    if not await ensure_admin(callback):
        return
    await state.set_state(AdminStates.import_host)
    await callback.message.edit_text(
        "📥 <b>Импорт серверов с 3x-ui</b>\n\n"
        "Введи <b>IP или домен</b> VPS сервера, где установлен 3x-ui.\n\n"
        "Бот подключится к 3x-ui API (порт 2053), "
        "заберёт все inbounds и создаст сервера в боте автоматически.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.import_host)
async def admin_import_inbounds_host(message: Message, state: FSMContext):
    if not await ensure_admin(message):
        return
    host = message.text.strip()
    msg = await message.answer(f"🔍 Подключаюсь к {host}:2053...")

    try:
        inbounds = await v2ray_service.fetch_inbounds(host)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка подключения: {e}")
        await state.clear()
        return

    if not inbounds:
        await msg.edit_text(
            f"❌ Не удалось получить inbounds с {host}.\n"
            f"Проверь:\n"
            f"• Запущен ли 3x-ui\n"
            f"• Доступен ли порт 2053\n"
            f"• Логин/пароль в .env (V2RAY_USER, V2RAY_PASS)",
            reply_markup=admin_keyboard(),
        )
        await state.clear()
        return

    imported = 0
    skipped = 0
    errors = 0
    text = f"📥 <b>Импорт с {host}</b>\n\n"

    for inbound in inbounds:
        parsed = await v2ray_service.parse_inbound(inbound, host)
        if not parsed:
            errors += 1
            continue

        # Проверяем, нет ли уже такого сервера (по хосту + порту)
        existing = await get_all_servers()
        dup = any(
            s.host == parsed["host"] and s.port == parsed["port"]
            for s in existing
        )
        if dup:
            skipped += 1
            text += f"⏭ {parsed['name']} ({parsed['host']}:{parsed['port']}) — уже есть\n"
            continue

        try:
            await create_server(**parsed)
            imported += 1
            text += f"✅ {parsed['name']} ({parsed['host']}:{parsed['port']}, {parsed['protocol']})\n"
        except Exception:
            errors += 1

    text += f"\n📊 Итого: импортировано <b>{imported}</b>, пропущено <b>{skipped}</b>, ошибок <b>{errors}</b>"
    await msg.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await state.clear()


# --- EXTEND SUBSCRIPTION ---

@router.message(Command("extend"))
async def cmd_extend(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Использование: /extend [telegram_id] [дней]")
        return
    try:
        tid = int(args[1])
        days = int(args[2])
    except ValueError:
        await message.answer("❌ ID и дни должны быть числами")
        return

    user = await get_user(tid)
    if not user:
        await message.answer("❌ Пользователь не найден")
        return

    # Берём план последней подписки или используем "1month"
    subs = await get_subscriptions(user.id)
    plan_code = subs[0].plan if subs else "1month"
    active = await get_active_subscription(user.id)
    if active:
        new_end = active.end_date + timedelta(days=days)
        sub = await create_subscription(user_id=user.id, plan=active.plan, end_date=new_end)
    else:
        new_end = datetime.now(timezone.utc) + timedelta(days=days)
        sub = await create_subscription(user_id=user.id, plan=plan_code, end_date=new_end)

    await message.answer(
        f"✅ Подписка продлена!\n"
        f"👤 Пользователь: <code>{tid}</code>\n"
        f"📅 Новая дата: {new_end.strftime('%d.%m.%Y')}",
        parse_mode="HTML",
    )


# --- USER CONFIGS ---

@router.message(Command("user_configs"))
async def cmd_user_configs(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /user_configs [telegram_id]")
        return
    try:
        tid = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом")
        return

    user = await get_user(tid)
    if not user:
        await message.answer("❌ Пользователь не найден")
        return

    configs = await get_active_configs(user.id)
    text = f"🔗 <b>Конфиги пользователя {tid}:</b> {len(configs)}\n\n"
    for c in configs:
        svr = f"сервер #{c.server_id}" if not hasattr(c, 'server') or not c.server else c.server.name
        text += f"• {svr} | UUID: <code>{c.uuid[:16]}...</code>\n"
        text += f"  До {c.expires_at.strftime('%d.%m.%Y')}\n"

    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


# --- TRAFFIC STATS ---

@router.message(Command("traffic"))
async def cmd_traffic(message: Message):
    if not await ensure_admin(message):
        return
    servers = await get_all_servers()
    configs = await get_all_active_configs()

    text = "📊 <b>Использование серверов:</b>\n\n"
    for s in servers:
        server_configs = [c for c in configs if c.server_id == s.id]
        users = len(set(c.user_id for c in server_configs))
        status = "✅" if s.is_active else "⛔"
        text += f"{status} <b>{s.name}</b> ({s.location or '?'})\n"
        text += f"   👤 {users} юзеров | 🔗 {len(server_configs)} конфигов\n"
        if s.traffic_limit > 0:
            pct = (s.traffic_used / s.traffic_limit) * 100
            text += f"   📊 Трафик: {s.traffic_used:.1f}/{s.traffic_limit} GB ({pct:.0f}%)\n"
        text += "\n"

    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


# --- BACKUP ---

@router.message(Command("backup"))
async def cmd_backup(message: Message):
    if not await ensure_admin(message):
        return
    import shutil, os
    is_sqlite = "sqlite" in config.DB_URL
    if is_sqlite:
        db_path = config.DB_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        if not os.path.exists(db_path):
            await message.answer("❌ Файл БД не найден")
            return
        backup_path = f"vpnbot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(db_path, backup_path)
        await message.answer(f"✅ БД сохранена: {backup_path}\nРазмер: {os.path.getsize(backup_path) / 1024:.1f} KB")
    else:
        await message.answer(
            "⚠️ Ручной бэкап для PostgreSQL не поддерживается.\n"
            "Используй: pg_dump -U vpnbot vpnbot > backup.sql",
        )


# --- HELP ---

@router.message(Command("admin_help"))
async def cmd_admin_help(message: Message):
    if not await ensure_admin(message):
        return
    text = (
        "👑 <b>Все админ-команды:</b>\n\n"
        "📊 <b>Статистика:</b>\n"
        "  /admin — открыть админ-панель\n"
        "  /stats — быстрая статистика\n"
        "  /traffic — нагрузка на сервера\n\n"
        "👤 <b>Пользователи:</b>\n"
        "  /find [id|@user] — найти пользователя\n"
        "  /ban [id] — заблокировать\n"
        "  /unban [id] — разблокировать\n"
        "  /give — выдать VPN (пошагово)\n"
        "  /extend [id] [дни] — продлить подписку\n"
        "  /user_configs [id] — конфиги пользователя\n\n"
        "💲 <b>Тарифы:</b>\n"
        "  /add_plan — добавить тариф\n"
        "  /edit_plan [id] [поле] [знач] — изменить\n"
        "  /del_plan [id] — удалить\n\n"
        "🌐 <b>Сервера:</b>\n"
        "  /server [id] — детали сервера\n"
        "  /server_toggle [id] — вкл/выкл\n"
        "  /server_del [id] — удалить\n"
        "  /check_server [id] — проверить 3x-ui на сервере\n"
        "  /import_inbounds — импорт всех inbounds с 3x-ui\n\n"
        "📢 <b>Прочее:</b>\n"
        "  /configs — все активные конфиги\n"
        "  /backup — сохранить копию БД\n"
        "  /admin_help — этот список\n\n"
        "💳 <b>Платежи:</b>\n"
        "  /payments — все платежи (последние 50)\n"
        "  /pending_payments — оплаченные без активации\n"
        "  /retry_payment [id] — повторная активация"
    )
    await message.answer(text, parse_mode="HTML")


# --- PAYMENT ADMIN COMMANDS ---

@router.message(Command("payments"))
async def cmd_payments(message: Message):
    if not await ensure_admin(message):
        return
    limit = 50
    payments = await get_all_payments(limit)
    if not payments:
        await message.answer("❌ Платежей нет")
        return

    text = f"💳 <b>Последние {limit} платежей:</b>\n\n"
    for p in payments:
        user = await get_user_by_id(p.user_id)
        tid = user.telegram_id if user else "?"
        icon = {"completed": "✅", "pending": "⏳", "cancelled": "❌"}.get(p.status, "❓")
        paid = f" ({p.paid_at.strftime('%d.%m %H:%M')})" if p.paid_at else ""
        text += (
            f"{icon} #{p.id} | <code>{tid}</code>\n"
            f"   {p.plan} | {p.amount}₽ | {p.status}{paid}\n\n"
        )
        if len(text) > 3500:
            text += "..."
            break
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(Command("pending_payments"))
async def cmd_pending_payments(message: Message):
    if not await ensure_admin(message):
        return
    payments = await get_pending_payments()
    # Filter: payments with status "completed" where user has NO active subscription
    text = "⚠️ <b>Оплаченные платежи БЕЗ активации:</b>\n\n"
    found = False
    for p in payments:
        user = await get_user_by_id(p.user_id)
        if not user:
            continue
        sub = await get_active_subscription(user.id)
        if not sub:
            found = True
            text += f"🆔 #{p.id} | <code>{user.telegram_id}</code>\n"
            text += f"   {p.plan} | {p.amount}₽ | {p.created_at.strftime('%d.%m %H:%M')}\n\n"
        if len(text) > 3500:
            text += "..."
            break
    if not found:
        text += "✅ Все оплаченные подписки активированы."
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(Command("retry_payment"))
async def cmd_retry_payment(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /retry_payment [payment_id]")
        return
    try:
        pid = uuid.UUID(args[1])
    except ValueError:
        await message.answer("❌ Неверный ID платежа")
        return

    payment = await get_payment(pid)
    if not payment:
        await message.answer("❌ Платёж не найден")
        return
    if payment.status != "completed":
        await message.answer(f"❌ Статус платежа: {payment.status}. Нужен «completed».")
        return

    try:
        result = await subscription_service.activate_subscription_after_payment(
            user_id=payment.user_id, plan_code=payment.plan,
        )
        if result["success"]:
            await message.answer(
                f"✅ Подписка активирована!\n"
                f"👤 user_id={payment.user_id}\n"
                f"📅 до {result['subscription'].end_date.strftime('%d.%m.%Y')}",
                parse_mode="HTML",
            )
        else:
            await message.answer(f"❌ Ошибка: {result.get('error', 'неизвестна')}")
    except Exception as e:
        logger.exception(f"Retry payment failed: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("pending_wallet"))
async def cmd_pending_wallet(message: Message):
    if not await ensure_admin(message):
        return
    payments = await get_pending_payments()
    wallet_pending = [p for p in payments if p.provider == "wallet"]
    if not wallet_pending:
        await message.answer("✅ Нет ожидающих оплат на кошелёк.")
        return
    text = "🏦 <b>Ожидают подтверждения (кошелёк):</b>\n\n"
    for p in wallet_pending[:20]:
        user = await get_user_by_id(p.user_id)
        tid = user.telegram_id if user else "?"
        text += (
            f"🆔 #{p.id} | <code>{tid}</code>\n"
            f"   {p.plan} | {p.amount}₽ | {p.created_at.strftime('%d.%m %H:%M')}\n"
            f"   Подтвердить: /confirm_payment {p.id}\n\n"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(Command("confirm_payment"))
async def cmd_confirm_payment(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /confirm_payment [payment_id]")
        return
    try:
        pid = uuid.UUID(args[1])
    except ValueError:
        await message.answer("❌ Неверный ID платежа")
        return
    payment = await get_payment(pid)
    if not payment:
        await message.answer("❌ Платёж не найден")
        return
    if payment.status != "pending":
        await message.answer(f"❌ Статус: {payment.status}. Ожидается «pending».")
        return
    await update_payment_status(pid, "completed")
    try:
        result = await subscription_service.activate_subscription_after_payment(
            user_id=payment.user_id, plan_code=payment.plan,
        )
        if result["success"]:
            await message.answer(
                f"✅ Платёж подтверждён! Подписка активирована.\n"
                f"👤 user_id={payment.user_id}\n"
                f"📅 до {result['subscription'].end_date.strftime('%d.%m.%Y')}",
                parse_mode="HTML",
            )
        else:
            await message.answer(f"❌ Ошибка активации: {result.get('error')}")
    except Exception as e:
        logger.exception(f"Confirm payment failed: {e}")
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("online"))
async def cmd_online(message: Message):
    if not await ensure_admin(message):
        return
    servers = await get_all_servers()
    if not servers:
        await message.answer("❌ Нет серверов.")
        return

    msg = await message.answer("🔄 Проверяю онлайн пользователей...")
    total_online = 0
    text = "🟢 <b>Онлайн пользователи:</b>\n\n"

    for srv in servers:
        if not srv.is_active:
            continue
        try:
            onlines = await v2ray_service.get_online_clients(srv.host)
            online_count = len(onlines)
            total_online += online_count
            status = "🟢" if online_count > 0 else "⚪"
            text += f"{status} <b>{srv.name}</b> ({srv.location or '?'}): <b>{online_count}</b> онлайн\n"
        except Exception:
            text += f"🔴 <b>{srv.name}</b> — нет ответа от API\n"

    text += f"\n📊 <b>Всего онлайн:</b> {total_online}"
    text += f"\n👥 <b>Всего пользователей:</b> {await get_users_count()}"
    text += f"\n✅ <b>Активных подписок:</b> {await get_active_users_count()}"
    await msg.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(Command("server_load"))
async def cmd_server_load(message: Message):
    if not await ensure_admin(message):
        return
    servers = await get_all_servers()
    if not servers:
        await message.answer("❌ Нет серверов.")
        return

    msg = await message.answer("🔄 Получаю нагрузку серверов...")
    text = "📊 <b>Нагрузка на сервера:</b>\n\n"

    for srv in servers:
        if not srv.is_active:
            text += f"⛔ <b>{srv.name}</b> — отключён\n\n"
            continue
        try:
            traffic = await v2ray_service.get_server_traffic(srv.host)
            up_gb = traffic["total_up"] / (1024**3)
            down_gb = traffic["total_down"] / (1024**3)
            total_gb = traffic["total"] / (1024**3)
            inbound_count = len(traffic["inbounds"])
            client_count = sum(i["clients"] for i in traffic["inbounds"])

            text += f"🌐 <b>{srv.name}</b> ({srv.location or '?'})\n"
            text += f"   📤 Отдано: <b>{up_gb:.2f} GB</b>\n"
            text += f"   📥 Принято: <b>{down_gb:.2f} GB</b>\n"
            text += f"   📊 Всего трафика: <b>{total_gb:.2f} GB</b>\n"
            text += f"   👥 Всего клиентов: <b>{client_count}</b>\n"
            text += f"   📦 Инбаундов: <b>{inbound_count}</b>\n"
            if srv.traffic_limit > 0:
                pct = (srv.traffic_used / srv.traffic_limit) * 100
                text += f"   📈 Лимит: {pct:.1f}%\n"
            text += "\n"
        except Exception:
            text += f"🔴 <b>{srv.name}</b> — нет ответа от 3x-ui API\n\n"

    await msg.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin_online")
async def callback_admin_online(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    await callback.answer()
    servers = await get_all_servers()
    if not servers:
        await callback.message.edit_text("❌ Нет серверов.", reply_markup=admin_keyboard())
        return

    await callback.message.edit_text("🔄 Проверяю онлайн пользователей...")
    total_online = 0
    text = "🟢 <b>Онлайн пользователи:</b>\n\n"

    for srv in servers:
        if not srv.is_active:
            continue
        try:
            onlines = await v2ray_service.get_online_clients(srv.host)
            online_count = len(onlines)
            total_online += online_count
            status = "🟢" if online_count > 0 else "⚪"
            text += f"{status} <b>{srv.name}</b> ({srv.location or '?'}): <b>{online_count}</b> онлайн\n"
        except Exception:
            text += f"🔴 <b>{srv.name}</b> — нет ответа от API\n"

    text += f"\n📊 <b>Всего онлайн:</b> {total_online}"
    text += f"\n👥 <b>Всего пользователей:</b> {await get_users_count()}"
    text += f"\n✅ <b>Активных подписок:</b> {await get_active_users_count()}"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin_server_load")
async def callback_admin_server_load(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    await callback.answer()
    servers = await get_all_servers()
    if not servers:
        await callback.message.edit_text("❌ Нет серверов.", reply_markup=admin_keyboard())
        return

    await callback.message.edit_text("🔄 Получаю нагрузку серверов...")
    text = "📊 <b>Нагрузка на сервера:</b>\n\n"

    for srv in servers:
        if not srv.is_active:
            text += f"⛔ <b>{srv.name}</b> — отключён\n\n"
            continue
        try:
            traffic = await v2ray_service.get_server_traffic(srv.host)
            up_gb = traffic["total_up"] / (1024**3)
            down_gb = traffic["total_down"] / (1024**3)
            total_gb = traffic["total"] / (1024**3)
            inbound_count = len(traffic["inbounds"])
            client_count = sum(i["clients"] for i in traffic["inbounds"])

            text += f"🌐 <b>{srv.name}</b> ({srv.location or '?'})\n"
            text += f"   📤 Отдано: <b>{up_gb:.2f} GB</b>\n"
            text += f"   📥 Принято: <b>{down_gb:.2f} GB</b>\n"
            text += f"   📊 Всего трафика: <b>{total_gb:.2f} GB</b>\n"
            text += f"   👥 Всего клиентов в 3x-ui: <b>{client_count}</b>\n"
            text += f"   📦 Инбаундов: <b>{inbound_count}</b>\n"
            text += "\n"
        except Exception:
            text += f"🔴 <b>{srv.name}</b> — нет ответа от 3x-ui API\n\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


# ─── VPS Management ─────────────────────────────────────

@router.callback_query(F.data == "admin_vps_list")
async def callback_admin_vps_list(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    from app.services.vps_deploy import load_vps_servers

    servers = load_vps_servers()
    text = "🌐 <b>Мои VPS сервера:</b>\n\n"
    if not servers:
        text += "Нет добавленных серверов.\n\n"
        text += "Нажми «➕ Добавить VPS» чтобы добавить. "
        text += "Порт SSH по умолчанию: 22."
    else:
        for i, s in enumerate(servers, 1):
            text += f"{i}. <b>{s.get('name', 'VPS')}</b>\n"
            text += f"   📍 {s.get('location', '?')} | 🌐 {s['ip']}:{s.get('port', 22)}\n"
            text += f"   🔑 Пароль: <code>{s.get('password', '')[:4]}...{s.get('password', '')[-4:]}</code>\n\n"

    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if servers:
        for i, s in enumerate(servers):
            builder.button(text=f"🚀 Установить 3x-ui: {s.get('name', s['ip'])}",
                           callback_data=f"admin_vps_deploy_{i}")
    builder.button(text="➕ Добавить VPS", callback_data="admin_vps_add")
    builder.button(text="🔄 Проверить все", callback_data="admin_vps_check")
    builder.button(text="◀ Назад", callback_data="admin")
    builder.adjust(1)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_vps_deploy_"))
async def callback_admin_vps_deploy(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    await callback.answer()
    from app.services.vps_deploy import load_vps_servers, install_3xui_on_server

    idx = int(callback.data.split("_")[-1])
    servers = load_vps_servers()
    if idx < 0 or idx >= len(servers):
        await callback.message.edit_text("❌ Сервер не найден.", reply_markup=admin_keyboard())
        return

    target = servers[idx]
    ip = target["ip"]
    await callback.message.edit_text(
        f"🔄 Устанавливаю 3x-ui на {ip} ({target.get('name', '')})...\n"
        f"⏳ Это может занять 2-3 минуты."
    )

    result = await install_3xui_on_server(ip, target["password"], target.get("port", 22))

    if result["success"]:
        text = (
            f"✅ <b>3x-ui установлена на {ip}!</b>\n\n"
            f"🌐 Панель: <code>http://{ip}:2055</code>\n"
            f"🔐 Логин: admin | Пароль: admin\n\n"
            f"⚠️ <b>Сразу смени пароль в панели!</b>\n\n"
            f"Теперь импортируй сервер в бота:\n"
            f"/admin → «Импорт с 3x-ui» → введи {ip}"
        )
    else:
        text = (
            f"❌ <b>Ошибка установки на {ip}</b>\n\n"
            f"{result.get('error', 'Неизвестная ошибка')}\n\n"
            f"Проверь:\n"
            f"• IP доступен?\n"
            f"• Пароль правильный?\n"
            f"• Ubuntu 22.04/24.04?"
        )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin_vps_add")
async def callback_admin_vps_add(callback: CallbackQuery, state: FSMContext):
    if not await ensure_admin(callback):
        return
    await state.set_state(AdminStates.vps_add_ip)
    await callback.message.edit_text(
        "🌐 <b>Добавление VPS сервера</b>\n\n"
        "Введи <b>IP адрес</b> сервера:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.vps_add_ip)
async def admin_vps_add_ip(message: Message, state: FSMContext):
    ip = message.text.strip()
    await state.update_data(ip=ip)
    await state.set_state(AdminStates.vps_add_password)
    await message.answer("Введи <b>root пароль</b> сервера:", parse_mode="HTML")


@router.message(AdminStates.vps_add_password)
async def admin_vps_add_password(message: Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    await state.set_state(AdminStates.vps_add_location)
    await message.answer("Введи <b>локацию</b> (например: Netherlands, Germany):", parse_mode="HTML")


@router.message(AdminStates.vps_add_location)
async def admin_vps_add_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    await state.set_state(AdminStates.vps_add_name)
    await message.answer("Введи <b>название</b> сервера (например: Amsterdam NL-1):", parse_mode="HTML")


@router.message(AdminStates.vps_add_name)
async def admin_vps_add_name(message: Message, state: FSMContext):
    from app.services.vps_deploy import load_vps_servers, save_vps_servers

    data = await state.get_data()
    servers = load_vps_servers()
    servers.append({
        "ip": data["ip"],
        "password": data["password"],
        "location": data["location"],
        "name": message.text.strip(),
        "port": 22,
    })
    save_vps_servers(servers)
    await state.clear()
    await message.answer(
        f"✅ <b>VPS сервер добавлен!</b>\n\n"
        f"🌐 IP: <code>{data['ip']}</code>\n"
        f"📍 Локация: {data['location']}\n"
        f"📛 Название: {message.text.strip()}\n"
        f"🔌 Порт SSH: 22\n\n"
        f"Теперь можешь установить 3x-ui:\n"
        f"/deploy_vps {data['ip']}",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


@router.message(Command("deploy_vps"))
async def cmd_deploy_vps(message: Message):
    if not await ensure_admin(message):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /deploy_vps [IP]")
        return

    from app.services.vps_deploy import load_vps_servers, install_3xui_on_server

    ip = args[1].strip()
    servers = load_vps_servers()
    target = next((s for s in servers if s["ip"] == ip), None)
    if not target:
        await message.answer(f"❌ VPS с IP {ip} не найден в servers.json.\n"
                             f"Сначала добавь через админку: /admin → «VPS сервера» → «Добавить VPS»")
        return

    msg = await message.answer(f"🔄 Устанавливаю 3x-ui на {ip}...\n⏳ Это может занять 2-3 минуты.")

    result = await install_3xui_on_server(ip, target["password"], target.get("port", 22))

    if result["success"]:
        text = (
            f"✅ <b>3x-ui установлена на {ip}!</b>\n\n"
            f"🌐 Панель: <code>http://{ip}:2055</code>\n"
            f"🔐 Логин: admin | Пароль: admin\n\n"
            f"⚠️ <b>Сразу смени пароль в панели!</b>\n\n"
            f"Теперь импортируй сервер в бота:\n"
            f"/admin → «Импорт с 3x-ui» → введи {ip}"
        )
    else:
        text = (
            f"❌ <b>Ошибка установки на {ip}</b>\n\n"
            f"{result.get('error', 'Неизвестная ошибка')}\n\n"
            f"Проверь:\n"
            f"• IP доступен?\n"
            f"• Пароль правильный?\n"
            f"• Ubuntu 22.04/24.04?\n"
            f"• Порт SSH: 22?"
        )

    await msg.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin_vps_check")
async def callback_admin_vps_check(callback: CallbackQuery):
    if not await ensure_admin(callback):
        return
    from app.services.vps_deploy import load_vps_servers, check_server_ssh

    servers = load_vps_servers()
    if not servers:
        await callback.message.edit_text("❌ Нет VPS серверов.", reply_markup=admin_keyboard())
        await callback.answer()
        return

    await callback.message.edit_text("🔄 Проверяю доступность VPS серверов...")
    text = "🔍 <b>Статус VPS серверов:</b>\n\n"
    for s in servers:
        try:
            status = await check_server_ssh(s["ip"], s["password"], s.get("port", 22))
            if status["alive"]:
                text += f"✅ <b>{s.get('name', 'VPS')}</b> ({s['ip']}) — ONLINE\n"
            else:
                text += f"❌ <b>{s.get('name', 'VPS')}</b> ({s['ip']}) — OFFLINE: {status.get('error', 'таймаут')}\n"
        except Exception:
            text += f"❌ <b>{s.get('name', 'VPS')}</b> ({s['ip']}) — ошибка проверки\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_keyboard())
    await callback.answer()

