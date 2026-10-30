"""Хендлеры оплаты: оформление, счёт, проверка статуса, отмена, выдача.

Все решения о деньгах принимает ``PaymentService`` — хендлер только
показывает результат и физически выдаёт материалы. Выдача намеренно
отделена от подтверждения оплаты: покупка создаётся «не выданной», а
``delivered_at`` проставляется после успешной отправки сообщения со
ссылкой. Сбой Telegram API при этом не означает потерю оплаченного
товара — спасает кнопка «Повторить выдачу».

Материалы хранятся ссылкой (``products.file_url``), поэтому выдача — это
сообщение с inline-кнопкой, а не загрузка файла: бот не отдаёт чужие
ссылки в тексте и не упирается в лимит Telegram на размер документа.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.handlers.common import safe_edit
from bot.i18n import translate
from bot.keyboards.callback_data import (
    NavCallback,
    OrderCallback,
    ProductCallback,
)
from bot.keyboards.inline import (
    checkout_confirm_keyboard,
    checkout_keyboard,
    delivery_keyboard,
)
from bot.services.errors import ServiceError
from bot.services.payment_service import DeliveryItem, PaymentService
from bot.services.product_service import ProductService
from bot.services.user_service import UserProfile
from bot.states.registration import ShopStates

logger = logging.getLogger(__name__)

router = Router(name="payment")


@router.callback_query(ProductCallback.filter(F.action == "buy"))
async def handle_buy_product(
    callback: CallbackQuery,
    callback_data: ProductCallback,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
    payment_service: PaymentService,
    state: FSMContext,
) -> None:
    """Оформляет заказ и просит подтвердить создание счёта."""
    try:
        card = await product_service.get_for_purchase(callback_data.slug)
        await product_service.require_not_owned(profile.tg_id, card)
        checkout = await payment_service.start_checkout(
            user_id=profile.tg_id, product=card
        )
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    await state.set_state(ShopStates.confirming_order)
    await state.update_data(order_id=checkout.order_id, slug=card.slug)
    await safe_edit(
        callback.message,
        translate(
            "product.checkout_body",
            language,
            title=card.title,
            price=checkout.total_label,
        ),
        checkout_confirm_keyboard(checkout.order_id, language),
    )
    await callback.answer()


@router.callback_query(OrderCallback.filter(F.action == "create_invoice"))
async def handle_create_invoice(
    callback: CallbackQuery,
    callback_data: OrderCallback,
    profile: UserProfile,
    language: str,
    payment_service: PaymentService,
    state: FSMContext,
) -> None:
    """Создаёт счёт в YooKassa и отдаёт ссылку на оплату."""
    try:
        link = await payment_service.create_payment(
            user_id=profile.tg_id, order_id=callback_data.order_id
        )
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    await state.set_state(ShopStates.awaiting_payment)
    await safe_edit(
        callback.message,
        translate("pay.invoice_created", language, price=link.total_label),
        checkout_keyboard(
            callback_data.order_id,
            language,
            confirmation_url=link.confirmation_url,
        ),
    )
    await callback.answer()


@router.callback_query(OrderCallback.filter(F.action == "check_payment"))
async def handle_check_payment(
    callback: CallbackQuery,
    callback_data: OrderCallback,
    bot: Bot,
    profile: UserProfile,
    language: str,
    payment_service: PaymentService,
    state: FSMContext,
) -> None:
    """Переспрашивает провайдера и, если оплачено, выдаёт товары.

    Webhook может запаздывать (или быть недоступен в dev-среде), поэтому
    кнопка опрашивает YooKassa напрямую. ``_settle_order`` в сервисе
    атомарна: одновременные webhook и нажатие кнопки не создадут дублей
    покупок.
    """
    try:
        paid = await payment_service.sync_payment_status(
            user_id=profile.tg_id, order_id=callback_data.order_id
        )
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    if not paid:
        await callback.answer(translate("pay.pending", language))
        return
    await state.clear()
    await deliver_order(
        bot,
        chat_id=profile.tg_id,
        order_id=callback_data.order_id,
        language=language,
        payment_service=payment_service,
    )
    await callback.answer(translate("pay.success", language))


@router.callback_query(OrderCallback.filter(F.action == "cancel"))
async def handle_cancel_order(
    callback: CallbackQuery,
    callback_data: OrderCallback,
    profile: UserProfile,
    language: str,
    payment_service: PaymentService,
    state: FSMContext,
) -> None:
    """Отменяет неоплаченный заказ."""
    try:
        canceled = await payment_service.cancel_order(
            user_id=profile.tg_id, order_id=callback_data.order_id
        )
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    await state.clear()
    await safe_edit(
        callback.message,
        (
            translate("pay.canceled", language, order_id=callback_data.order_id)
            if canceled
            else translate("pay.already_paid", language)
        ),
        None,
    )
    await callback.answer()


@router.callback_query(OrderCallback.filter(F.action == "repeat_delivery"))
async def handle_repeat_delivery(
    callback: CallbackQuery,
    callback_data: OrderCallback,
    bot: Bot,
    profile: UserProfile,
    language: str,
    payment_service: PaymentService,
) -> None:
    """Повторно выдаёт материалы, если отправка упала."""
    sent = await deliver_order(
        bot,
        chat_id=profile.tg_id,
        order_id=callback_data.order_id,
        language=language,
        payment_service=payment_service,
    )
    if not sent:
        await callback.answer(translate("delivery.failed", language))
        return
    await callback.answer()


@router.callback_query(NavCallback.filter(F.action == "back_menu"))
async def handle_back_to_menu(
    callback: CallbackQuery,
    language: str,
    state: FSMContext,
) -> None:
    """Возврат в главное меню: снимает FSM-состояние покупки."""
    await state.clear()
    await safe_edit(
        callback.message,
        translate("cmd.help", language),
        None,
    )
    await callback.answer()


async def deliver_order(
    bot: Bot,
    *,
    chat_id: int,
    order_id: int,
    language: str,
    payment_service: PaymentService,
) -> bool:
    """Выдаёт материалы оплаченного заказа и подтверждает выдачу.

    Args:
        bot: Отправка идёт в чат, а не в редактируемое сообщение.
        chat_id: Куда отправлять.
        order_id: Оплаченный заказ.
        language: Язык подписей.
        payment_service: Сервис, дающий позиции и принимающий выдачу.

    Returns:
        ``True``, если выдано хотя бы что-то.
    """
    try:
        items = await payment_service.delivery_items(
            user_id=chat_id, order_id=order_id
        )
    except ServiceError as error:
        logger.warning("Выдача заказа %s невозможна: %s", order_id, error)
        await bot.send_message(chat_id, error.user_message)
        return False
    if not items:
        await bot.send_message(
            chat_id, translate("pay.purchases_empty", language)
        )
        return False
    await bot.send_message(
        chat_id, translate("delivery.header", language, order_id=order_id)
    )
    delivered: list[int] = []
    for index, item in enumerate(items, start=1):
        if await _send_item(bot, chat_id, item, language, index):
            delivered.append(item.purchase_id)
    if delivered:
        await payment_service.mark_delivered(delivered)
    if len(delivered) < len(items):
        await bot.send_message(
            chat_id,
            translate("delivery.failed", language),
            reply_markup=checkout_keyboard(
                order_id, language, show_payment=False
            ),
        )
    return bool(delivered)


async def _send_item(
    bot: Bot,
    chat_id: int,
    item: DeliveryItem,
    language: str,
    index: int,
) -> bool:
    """Отправляет одну позицию; при сбое Telegram — ``False``.

    Покупка при неудаче остаётся не выданной, поэтому повтор кнопки
    дошлёт именно недостающие материалы, а не весь заказ заново.
    """
    try:
        await bot.send_message(
            chat_id,
            translate("delivery.item", language, index=index, title=item.title),
            reply_markup=delivery_keyboard(item.file_url, language),
        )
        return True
    except TelegramAPIError as error:
        logger.warning(
            "Не удалось выдать товар %s пользователю %s: %s",
            item.product_id,
            chat_id,
            error,
        )
        return False
