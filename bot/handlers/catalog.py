"""Хендлеры витрины: каталог, карточка товара, «мои покупки».

Файл отвечает за inline-навигацию (стрелки страниц, кнопки товаров,
выдача ссылки на материалы). Команды и reply-меню под полем ввода — в
:mod:`bot.handlers.commands`, но они вызывают общие функции
:func:`render_catalog` и :func:`render_purchases`: «Каталог» по кнопке и
по ``/catalog`` обязан выглядеть одинаково.

Здесь только «сборка ответа»: выборки дают сервисы, тексты — i18n,
кнопки — ``bot.keyboards``. Прямых запросов к БД нет, как требует
соглашение проекта.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.handlers.common import safe_edit
from bot.i18n import translate
from bot.keyboards.callback_data import (
    NavCallback,
    PageCallback,
    ProductCallback,
)
from bot.keyboards.inline import (
    catalog_keyboard,
    delivery_keyboard,
    product_keyboard,
    purchase_keyboard,
)
from bot.services.errors import ServiceError
from bot.services.product_service import (
    ProductCard,
    ProductService,
    PurchaseInfo,
)
from bot.services.user_service import UserProfile
from bot.states.registration import ShopStates

logger = logging.getLogger(__name__)

router = Router(name="catalog")


def product_text(card: ProductCard, language: str) -> str:
    """Текст карточки товара: название, описание, цена.

    ``file_url`` в карточке отсутствует по определению (см.
    :class:`ProductCard`), поэтому текст безопасен для показа любому.
    """
    lines = [translate("product.title", language, title=card.title)]
    if card.description:
        lines.append(card.description)
    lines.append(
        translate("product.price", language, price=card.formatted_price)
    )
    return "\n\n".join(lines)


async def render_catalog(
    target: Message,
    language: str,
    product_service: ProductService,
    *,
    page: int = 0,
) -> None:
    """Отправляет страницу каталога ответом на сообщение."""
    products = await product_service.list_catalog()
    if not products:
        await target.answer(translate("cmd.catalog_empty", language))
        return
    await target.answer(
        translate("menu.catalog", language),
        reply_markup=catalog_keyboard(products, language, page=page),
    )


async def open_product_card(
    target: Message,
    *,
    slug: str,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
) -> None:
    """Открывает карточку товара сообщением в чат (deep-link ``/start``).

    Args:
        target: Сообщение, ответом на которое выступаем.
        slug: Идентификатор товара из аргументов команды.
        profile: Профиль покупателя (нужен для проверки «уже куплено»).
        language: Язык ответа.
        product_service: Сервис витрины из middleware.
    """
    try:
        card = await product_service.get_for_purchase(slug)
    except ServiceError as error:
        await target.answer(error.user_message)
        return
    owned = not await is_free_to_buy(product_service, profile.tg_id, card)
    await target.answer(
        product_text(card, language),
        reply_markup=product_keyboard(card, language, owned=owned),
    )


async def is_free_to_buy(
    service: ProductService, user_id: int, card: ProductCard
) -> bool:
    """Можно ли пользователю купить товар (ещё не куплен)."""
    try:
        await service.require_not_owned(user_id, card)
    except ServiceError:
        return False
    return True


def purchases_text(purchases: list[PurchaseInfo], language: str) -> str:
    """Список покупок текстом: заголовок с числом и строки товаров."""
    lines = [translate("purchases.header", language, count=len(purchases))]
    for row in purchases:
        lines.append(
            translate(
                "purchases.item",
                language,
                title=row.card.title,
                price=row.formatted_price,
            )
        )
    return "\n".join(lines)


def purchases_markup(row: PurchaseInfo, language: str) -> InlineKeyboardMarkup:
    """Кнопки последней покупки: «Скачать» и, если не выдано, «Повторить».

    ``order_id`` передаётся только для не выданных покупок: кнопка
    повторной выдачи иначе вела бы к пустому результату.
    """
    return purchase_keyboard(
        row.card.slug,
        language,
        order_id=None if row.delivered else row.order_id,
    )


async def render_purchases(
    event: CallbackQuery | Message,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
) -> None:
    """Показывает «Мои покупки» для любого типа события.

    Args:
        event: Нажатие inline-кнопки либо сообщение reply-меню/команды.
        profile: Профиль покупателя.
        language: Язык ответа.
        product_service: Сервис витрины из middleware.
    """
    purchases = await product_service.list_purchases(profile.tg_id)
    if not purchases:
        text = translate("purchases.empty", language)
        markup: InlineKeyboardMarkup | None = None
    else:
        text = purchases_text(purchases, language)
        markup = purchases_markup(purchases[0], language)
    if isinstance(event, CallbackQuery):
        await safe_edit(event.message, text, markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


@router.callback_query(NavCallback.filter(F.action == "catalog"))
async def handle_catalog_callback(
    callback: CallbackQuery,
    language: str,
    product_service: ProductService,
    state: FSMContext,
) -> None:
    """Открывает первую страницу каталога по inline-кнопке."""
    products = await product_service.list_catalog()
    if not products:
        await safe_edit(
            callback.message, translate("cmd.catalog_empty", language), None
        )
    else:
        await safe_edit(
            callback.message,
            translate("menu.catalog", language),
            catalog_keyboard(products, language, page=0),
        )
    # Состояние нужно, чтобы /cancel сбрасывал шаг покупки, а админские
    # FSM-опросы не перехватывали нажатия покупателя.
    await state.set_state(ShopStates.choosing_product)
    await callback.answer()


@router.callback_query(PageCallback.filter())
async def handle_catalog_page(
    callback: CallbackQuery,
    callback_data: PageCallback,
    language: str,
    product_service: ProductService,
) -> None:
    """Листает страницы каталога."""
    if callback_data.action == "noop":
        # Индикатор «2/5» не является действием.
        await callback.answer()
        return
    products = await product_service.list_catalog()
    await safe_edit(
        callback.message,
        translate("menu.catalog", language),
        catalog_keyboard(products, language, page=max(0, callback_data.page)),
    )
    await callback.answer()


@router.callback_query(ProductCallback.filter(F.action == "open"))
async def handle_open_product(
    callback: CallbackQuery,
    callback_data: ProductCallback,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
) -> None:
    """Карточка товара: «Купить» или «Скачать материалы», если куплено."""
    try:
        card = await product_service.get_for_purchase(callback_data.slug)
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    owned = not await is_free_to_buy(product_service, profile.tg_id, card)
    await safe_edit(
        callback.message,
        product_text(card, language),
        product_keyboard(card, language, owned=owned),
    )
    await callback.answer()


@router.callback_query(ProductCallback.filter(F.action == "get_file"))
async def handle_get_file(
    callback: CallbackQuery,
    callback_data: ProductCallback,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
) -> None:
    """Выдаёт ссылку на материалы купленного товара."""
    try:
        card = await product_service.get_for_purchase(callback_data.slug)
        file_url = await product_service.get_file_url_for_owner(
            profile.tg_id, card.id
        )
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    message = callback.message
    if isinstance(message, Message):
        await message.answer(
            translate("delivery.file", language, title=card.title),
            reply_markup=delivery_keyboard(file_url, language),
        )
    await callback.answer()


@router.callback_query(NavCallback.filter(F.action == "my_purchases"))
async def handle_my_purchases_callback(
    callback: CallbackQuery,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
) -> None:
    """«Мои покупки» по inline-кнопке."""
    await render_purchases(callback, profile, language, product_service)
