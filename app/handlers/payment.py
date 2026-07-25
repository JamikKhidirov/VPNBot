import uuid
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.database import get_user, get_user_by_id, get_plan, get_plans, get_payment, update_payment_status, get_pending_payments, get_all_payments
from app.utils.pricing import get_discount_text, get_plan_price_text, DISCOUNT_INFO
from app.keyboards.inline import (
    plans_keyboard, payment_methods_keyboard, payment_url_keyboard,
    back_to_menu_keyboard, main_menu_keyboard,
)
from app.services.payment import payment_service
from app.services.subscription import subscription_service
from app.services.v2ray import v2ray_service
from app.utils.helpers import format_date
from app.config import config

logger = logging.getLogger(__name__)

router = Router()

SUB_PORT = config.SUB_PORT

PENDING_PAYMENTS: dict[int, uuid.UUID] = {}


@router.callback_query(F.data == "buy")
async def callback_buy(callback: CallbackQuery):
    plans = await get_plans()
    if not plans:
        await callback.message.edit_text(
            "❌ Тарифы временно недоступны. Попробуй позже.",
            reply_markup=back_to_menu_keyboard(),
        )
        await callback.answer()
        return

    text = "🛒 <b>Выбери тариф:</b>\n\n"
    for plan in plans:
        if plan.code == "trial":
            text += f"🎁 <b>{plan.name}</b> — {plan.days} дней · Бесплатно\n\n"
        else:
            price_str = f"{int(plan.price)} ₽" if plan.price == int(plan.price) else f"{plan.price} ₽"
            discount = get_discount_text(plan.code, plan.price)
            text += f"• <b>{plan.name}</b> — {plan.days} дн. | {price_str}{discount}\n\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=plans_keyboard(plans))
    await callback.answer()


@router.callback_query(F.data.startswith("plan_"))
async def callback_select_plan(callback: CallbackQuery):
    plan_code = callback.data.replace("plan_", "")
    plan = await get_plan(plan_code)

    if not plan:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    if plan.price == 0 and plan_code == "trial":
        if user.trial_used:
            await callback.answer("Пробный период уже использован!", show_alert=True)
            return

        result = await subscription_service.activate_trial(callback.from_user.id)
        if result["success"]:
            sub_link = f"{config.SUB_URL}/sub/{user.token}" if user and user.token else "скоро будет"
            srv_count = result.get("servers_count", 1)
            text = (
                f"🎉 <b>Пробный период активирован!</b>\n\n"
                f"⏳ <b>{plan.days} дней бесплатного VPN</b>\n"
                f"🌐 Серверов: {srv_count}\n\n"
                f"📱 <b>Подписка для V2RayTun:</b>\n"
                f"<code>{sub_link}</code>\n\n"
                f"👇 Что делать:\n"
                f"1️⃣ Открой V2RayTun\n"
                f"2️⃣ Нажми «+» → «Подписка»\n"
                f"3️⃣ Вставь ссылку выше\n"
                f"4️⃣ Пользуйся! 🚀"
            )
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard(callback.from_user.id))
        else:
            await callback.message.edit_text(
                f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}",
                reply_markup=back_to_menu_keyboard(),
            )
        await callback.answer()
        return

    providers = payment_service.get_available_providers()
    if not providers:
        await callback.answer("Способы оплаты временно недоступны", show_alert=True)
        return

    price_str = f"{int(plan.price)} ₽" if plan.price == int(plan.price) else f"{plan.price} ₽"
    discount = get_discount_text(plan.code, plan.price)

    text = (
        f"🗓 <b>{plan.name}</b>\n"
        f"📆 Дней: {plan.days}\n"
    )
    if discount:
        info = DISCOUNT_INFO.get(plan_code)
        if info:
            text += f"💰 <s>{info['original']} ₽</s> <b>{price_str}</b>{discount}\n"
    else:
        text += f"💰 Цена: <b>{price_str}</b>\n"
    text += "\nВыбери способ оплаты:"

    await callback.message.edit_text(text, parse_mode="HTML",
                                     reply_markup=payment_methods_keyboard(plan_code, providers))
    await callback.answer()


@router.callback_query(F.data.startswith("pay_"))
async def callback_process_payment(callback: CallbackQuery):
    parts = callback.data.split("_", 2)
    if len(parts) != 3:
        await callback.answer("Ошибка", show_alert=True)
        return

    provider, plan_code = parts[1], parts[2]
    plan = await get_plan(plan_code)
    user = await get_user(callback.from_user.id)

    if not plan or not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    try:
        result = await payment_service.create_payment(
            user_id=user.id,
            amount=plan.price,
            plan=plan_code,
            provider=provider,
            description=f"VPN {plan.name}",
        )
        PENDING_PAYMENTS[callback.from_user.id] = result["payment"].id

        if provider == "wallet":
            wallet = result.get("wallet", {})
            text = (
                f"🏦 <b>Оплата на кошелёк</b>\n\n"
                f"🗓 Тариф: {plan.name}\n"
                f"💰 Сумма: <b>{int(plan.price)} ₽</b>\n"
                f"💳 Валюта: {wallet.get('currency', 'USDT (TRC20)')}\n\n"
                f"📥 <b>Адрес кошелька:</b>\n"
                f"<code>{wallet.get('address', '—')}</code>\n\n"
                f"📌 Отправь ровно <b>{int(plan.price)} ₽</b> в USDT на этот адрес\n\n"
                f"⏳ После оплаты нажми «Проверить оплату»\n"
                f"⚠️ Админ подтвердит вручную"
            )
            from app.keyboards.inline import payment_url_keyboard
            await callback.message.edit_text(text, parse_mode="HTML",
                                             reply_markup=payment_url_keyboard(""))
        else:
            text = (
                f"🧾 <b>Счёт на оплату</b>\n\n"
                f"🗓 Тариф: {plan.name}\n"
                f"💰 Сумма: {int(plan.price)} ₽\n"
                f"💳 Способ: {provider}\n\n"
                f"Нажми «Оплатить» и после оплаты «Проверить оплату»."
            )
            await callback.message.edit_text(text, parse_mode="HTML",
                                             reply_markup=payment_url_keyboard(result["pay_url"]))
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка создания платежа: {e}",
            reply_markup=back_to_menu_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "check_payment")
async def callback_check_payment(callback: CallbackQuery):
    payment_id = PENDING_PAYMENTS.get(callback.from_user.id)
    if not payment_id:
        await callback.answer("Нет активного платежа", show_alert=True)
        return

    status = await payment_service.check_payment_status(payment_id)
    if status == "completed":
        payment = await get_payment(payment_id)
        if payment:
            try:
                result = await subscription_service.activate_subscription_after_payment(
                    user_id=payment.user_id, plan_code=payment.plan,
                )
                if result["success"]:
                    buyer = await get_user_by_id(payment.user_id)
                    sub_link = f"{config.SUB_URL}/sub/{buyer.token}" if buyer and buyer.token else "скоро будет"
                    srv_count = result.get("servers_count", 1)

                    text = (
                        "✅ <b>Оплата прошла успешно!</b>\n\n"
                        f"🗓 Тариф: {payment.plan}\n"
                        f"📅 Действует до: {format_date(result['subscription'].end_date)}\n"
                        f"🌐 Серверов: {srv_count}\n\n"
                        f"📱 <b>Твоя подписка для V2RayTun:</b>\n"
                        f"<code>{sub_link}</code>\n\n"
                        f"👇 Что делать:\n"
                        f"1️⃣ Открой V2RayTun\n"
                        f"2️⃣ Нажми «+» → «Подписка»\n"
                        f"3️⃣ Вставь ссылку выше\n"
                        f"4️⃣ Нажми «Подключиться»\n\n"
                        f"🌐 Все твои сервера подгрузятся автоматически!"
                    )

                    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard(callback.from_user.id))
                    PENDING_PAYMENTS.pop(callback.from_user.id, None)

                    logger.info(
                        f"PAYMENT_ACTIVATED: user_id={payment.user_id} "
                        f"telegram_id={callback.from_user.id} "
                        f"plan={payment.plan} amount={payment.amount} "
                        f"payment_id={payment_id}"
                    )
                    await callback.answer()
                    return
                else:
                    logger.error(
                        f"PAYMENT_FAILED_ACTIVATION: user_id={payment.user_id} "
                        f"telegram_id={callback.from_user.id} "
                        f"plan={payment.plan} amount={payment.amount} "
                        f"payment_id={payment_id} error={result.get('error')}"
                    )
            except Exception as e:
                logger.exception(
                    f"PAYMENT_ACTIVATION_EXCEPTION: user_id={payment.user_id} "
                    f"telegram_id={callback.from_user.id} "
                    f"payment_id={payment_id} error={e}"
                )

        await callback.message.edit_text(
            "✅ Платёж подтверждён, но ошибка активации. Обратись в поддержку.",
            reply_markup=back_to_menu_keyboard(),
        )
        await callback.answer()
        return
    elif status == "pending":
        await callback.answer("⏳ Платёж ещё не оплачен. Попробуй позже.", show_alert=True)
        return
    else:
        await callback.answer(f"❌ Статус: {status}", show_alert=True)
        return

    await callback.answer()
