"""Админские хендлеры: товары, цены, рассылка, сводка.

Права проверяются один раз — корневыми фильтрами роутера
:class:`IsAdminFilter`. Это важнее, чем кажется: если бы проверку делал
каждый хендлер, достаточно забыть один декоратор, и обычный покупатель
попал бы в админский FSM-опрос. Для не-админа фильтр возвращает ``False``
и событие спокойно уходит в другие роутеры, поэтому админ-роутер
регистрируют первым.

Пошаговые опросы (название, описание, цена, ссылка) идут через FSM: поля
не влазят в одну команду, а разбор длинного текста ломается на первом же
переносе строк. Смена цены существующего товара использует отдельную
группу состояний :class:`ProductEditStates` — иначе шаг анкеты и шаг
правки не различить по одному лишь состоянию.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from db.models.product import Product

from bot.handlers.common import safe_edit
from bot.i18n import translate
from bot.keyboards.callback_data import (
    AdminCallback,
    ConfirmChoiceCallback,
    ProductCallback,
)
from bot.keyboards.inline import (
    admin_menu_keyboard,
    admin_products_keyboard,
    confirm_keyboard,
    toggle_keyboard,
)
from bot.services.errors import ServiceError
from bot.services.money import InvalidAmountError, format_price
from bot.services.payment_service import PaymentService
from bot.services.product_service import ProductCard, ProductService
from bot.services.user_service import UserProfile, UserService
from bot.states.registration import (
    BroadcastStates,
    ProductEditStates,
    ProductFormStates,
)

logger = logging.getLogger(__name__)

router = Router(name="admin")

CREATE_PRODUCT_TARGET = "create_product"
"""Цель кнопок подтверждения: «Да» создаёт товар, «Нет» отменяет анкету."""


class IsAdminFilter(BaseFilter):
    """Фильтр: пропускать только администраторов.

    Используется как корневой фильтр роутера
    (``router.message.filter(IsAdminFilter())``), поэтому проверяет права
    до подбора конкретного хендлера.
    """

    async def __call__(
        self,
        event: Message | CallbackQuery,
        profile: UserProfile | None = None,
    ) -> bool:
        """Args:
        event: Событие — aiogram всегда передаёт его первым позиционно.
        profile: Профиль из ``AuthMiddleware``; ``None`` для событий без
            пользователя.

        Returns:
            ``True`` только для администраторов.
        """
        return bool(profile and profile.is_admin)


router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.message(Command("admin"))
@router.callback_query(AdminCallback.filter(F.action == "menu"))
async def handle_admin_menu(
    event: Message | CallbackQuery,
    language: str,
) -> None:
    """Главное админ-меню."""
    text = translate("admin.menu", language)
    markup = admin_menu_keyboard(language)
    if isinstance(event, CallbackQuery):
        await safe_edit(event.message, text, markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


@router.message(Command("cancel"))
async def handle_admin_cancel(
    message: Message,
    language: str,
    state: FSMContext,
) -> None:
    """``/cancel`` внутри админского опроса: сброс FSM и возврат в меню.

    Для администратора этот хендлер перекрывает общий ``/cancel`` из
    :mod:`bot.handlers.commands` — так выход из анкеты сразу показывает
    админ-меню.
    """
    await state.clear()
    await message.answer(
        translate("admin.cancelled", language),
        reply_markup=admin_menu_keyboard(language),
    )


@router.callback_query(AdminCallback.filter(F.action == "stats"))
async def handle_admin_stats(
    callback: CallbackQuery,
    language: str,
    user_service: UserService,
    product_service: ProductService,
    payment_service: PaymentService,
) -> None:
    """Сводка: пользователи, товары, оплаченные заказы, выручка."""
    users = await user_service.count_active()
    products = await product_service.count_active()
    orders, revenue_kopecks = await payment_service.count_stats()
    await safe_edit(
        callback.message,
        translate(
            "admin.stats",
            language,
            users=users,
            products=products,
            orders=orders,
            revenue=format_price(revenue_kopecks),
        ),
        admin_menu_keyboard(language),
    )
    await callback.answer()


@router.callback_query(AdminCallback.filter(F.action == "products"))
@router.message(Command("products"))
async def handle_admin_products(
    event: Message | CallbackQuery,
    language: str,
    product_service: ProductService,
) -> None:
    """Список всех товаров, включая снятые с продажи."""
    products = [
        ProductCard.from_model(product)
        for product in await product_service.list_all(include_hidden=True)
    ]
    if not products:
        text = translate("cmd.catalog_empty", language)
        markup = admin_menu_keyboard(language)
    else:
        text = translate("admin.products_header", language, count=len(products))
        markup = admin_products_keyboard(products, language)
    if isinstance(event, CallbackQuery):
        await safe_edit(event.message, text, markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


@router.callback_query(AdminCallback.filter(F.action == "add_product"))
@router.message(Command("add_product"))
async def handle_add_product_start(
    event: Message | CallbackQuery,
    language: str,
    state: FSMContext,
) -> None:
    """Начинает анкету нового товара: первый вопрос — название."""
    await state.clear()
    await state.set_state(ProductFormStates.waiting_title)
    text = translate("admin.ask_title", language)
    if isinstance(event, CallbackQuery):
        await safe_edit(event.message, text, None)
        await event.answer()
    else:
        await event.answer(text)


@router.message(ProductFormStates.waiting_title, F.text)
async def handle_product_title(
    message: Message,
    language: str,
    state: FSMContext,
) -> None:
    """Поле анкеты «название»: пустое название недопустимо."""
    title = (message.text or "").strip()
    if not title:
        await message.answer(translate("admin.ask_title", language))
        return
    await state.update_data(title=title)
    await state.set_state(ProductFormStates.waiting_description)
    await message.answer(translate("admin.ask_description", language))


@router.message(ProductFormStates.waiting_description, F.text)
async def handle_product_description(
    message: Message,
    language: str,
    state: FSMContext,
) -> None:
    """Поле анкеты «описание»: пустое значение допустимо."""
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(ProductFormStates.waiting_price)
    await message.answer(translate("admin.ask_price", language))


@router.message(ProductFormStates.waiting_price, F.text)
async def handle_product_price(
    message: Message,
    language: str,
    state: FSMContext,
) -> None:
    """Поле анкеты «цена»: строка проверяется парсером копеек."""
    raw = (message.text or "").strip()
    try:
        ProductService.parse_price(raw)
    except InvalidAmountError:
        await message.answer(translate("admin.bad_price", language))
        return
    await state.update_data(price=raw)
    await state.set_state(ProductFormStates.waiting_file_url)
    await message.answer(translate("admin.ask_file_url", language))


@router.message(ProductFormStates.waiting_file_url, F.text)
async def handle_product_file_url(
    message: Message,
    language: str,
    state: FSMContext,
) -> None:
    """Поле анкеты «ссылка»: после него — подтверждение создания."""
    file_url = (message.text or "").strip()
    if not file_url:
        await message.answer(translate("admin.ask_file_url", language))
        return
    data = await state.get_data()
    await state.update_data(file_url=file_url)
    await state.set_state(ProductFormStates.confirming)
    await message.answer(
        translate(
            "admin.confirm_create",
            language,
            title=data.get("title", ""),
            price=data.get("price", ""),
            file_url=file_url,
        ),
        reply_markup=confirm_keyboard(CREATE_PRODUCT_TARGET, language=language),
    )


@router.callback_query(
    ConfirmChoiceCallback.filter(F.target == CREATE_PRODUCT_TARGET)
)
async def handle_confirm_create_product(
    callback: CallbackQuery,
    callback_data: ConfirmChoiceCallback,
    language: str,
    state: FSMContext,
    product_service: ProductService,
) -> None:
    """Создаёт товар после «Да» и отменяет анкету после «Нет».

    Данные берутся из FSM, а не из callback-данных: название и описание
    не влазят в лимит Telegram в 64 байта.
    """
    data = await state.get_data()
    await state.clear()
    if not callback_data.approved:
        await safe_edit(
            callback.message,
            translate("admin.cancelled", language),
            admin_menu_keyboard(language),
        )
        await callback.answer()
        return
    try:
        product = await product_service.create_product(
            title=data.get("title", ""),
            description=data.get("description", ""),
            price_raw=data.get("price", ""),
            file_url=data.get("file_url", ""),
        )
    except (ServiceError, InvalidAmountError, ValueError) as error:
        await safe_edit(
            callback.message,
            getattr(error, "user_message", str(error)),
            admin_menu_keyboard(language),
        )
        await callback.answer()
        return
    await safe_edit(
        callback.message,
        translate(
            "admin.created",
            language,
            title=product.title,
            slug=product.slug,
        ),
        admin_menu_keyboard(language),
    )
    await callback.answer()


@router.callback_query(AdminCallback.filter(F.action == "edit"))
async def handle_admin_edit_product(
    callback: CallbackQuery,
    callback_data: AdminCallback,
    language: str,
    product_service: ProductService,
) -> None:
    """Карточка товара для админских действий (скрыть/цена)."""
    try:
        product = await product_service.get_any(callback_data.payload)
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    await safe_edit(
        callback.message,
        admin_product_text(product, language),
        toggle_keyboard(product.slug, language, is_active=product.is_active),
    )
    await callback.answer()


@router.callback_query(ProductCallback.filter(F.action.in_(["hide", "show"])))
async def handle_toggle_product(
    callback: CallbackQuery,
    callback_data: ProductCallback,
    language: str,
    product_service: ProductService,
) -> None:
    """Снимает товар с продажи или возвращает его в каталог."""
    activate = callback_data.action == "show"
    try:
        product = await product_service.set_active(callback_data.slug, activate)
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    await safe_edit(
        callback.message,
        translate(
            "admin.toggled",
            language,
            title=product.title,
            state=translate(
                "admin.state_active" if activate else "admin.state_hidden",
                language,
            ),
        ),
        toggle_keyboard(product.slug, language, is_active=product.is_active),
    )
    await callback.answer()


@router.callback_query(ProductCallback.filter(F.action == "edit_price"))
async def handle_edit_price_start(
    callback: CallbackQuery,
    callback_data: ProductCallback,
    language: str,
    state: FSMContext,
    product_service: ProductService,
) -> None:
    """Готовит смену цены: запоминаем slug и спрашиваем новое значение."""
    try:
        product = await product_service.get_any(callback_data.slug)
    except ServiceError as error:
        await callback.answer(error.user_message, show_alert=True)
        return
    await state.clear()
    await state.set_state(ProductEditStates.waiting_value)
    await state.update_data(edit_slug=product.slug)
    await safe_edit(
        callback.message,
        translate(
            "admin.ask_new_price",
            language,
            title=product.title,
            price=format_price(product.price_kopecks, product.currency),
        ),
        None,
    )
    await callback.answer()


@router.message(ProductEditStates.waiting_value, F.text)
async def handle_edit_price_value(
    message: Message,
    language: str,
    state: FSMContext,
    product_service: ProductService,
) -> None:
    """Применяет новую цену товара."""
    data = await state.get_data()
    slug = data.get("edit_slug") or ""
    try:
        product = await product_service.update_price(slug, message.text or "")
    except InvalidAmountError:
        await message.answer(translate("admin.bad_price", language))
        return
    except ServiceError as error:
        await state.clear()
        await message.answer(error.user_message)
        return
    await state.clear()
    await message.answer(
        translate(
            "admin.price_updated",
            language,
            title=product.title,
            price=format_price(product.price_kopecks, product.currency),
        ),
        reply_markup=admin_menu_keyboard(language),
    )


@router.callback_query(AdminCallback.filter(F.action == "broadcast"))
@router.message(Command("broadcast"))
async def handle_broadcast_start(
    event: Message | CallbackQuery,
    language: str,
    state: FSMContext,
) -> None:
    """Начинает рассылку: запрашивает текст сообщения."""
    await state.clear()
    await state.set_state(BroadcastStates.waiting_message)
    text = translate("admin.ask_broadcast", language)
    if isinstance(event, CallbackQuery):
        await safe_edit(event.message, text, None)
        await event.answer()
    else:
        await event.answer(text)


@router.message(BroadcastStates.waiting_message, F.text)
async def handle_broadcast_text(
    message: Message,
    language: str,
    state: FSMContext,
    user_service: UserService,
) -> None:
    """Запоминает текст и спрашивает подтверждение с числом адресатов."""
    text = (message.text or "").strip()
    if not text:
        await message.answer(translate("admin.ask_broadcast", language))
        return
    recipients = await user_service.active_user_ids()
    await state.update_data(text=text)
    await state.set_state(BroadcastStates.confirming)
    await message.answer(
        translate("admin.broadcast_confirm", language, count=len(recipients)),
        reply_markup=confirm_keyboard("broadcast", language=language),
    )


@router.callback_query(ConfirmChoiceCallback.filter(F.target == "broadcast"))
async def handle_broadcast_confirm(
    callback: CallbackQuery,
    callback_data: ConfirmChoiceCallback,
    bot: Bot,
    language: str,
    state: FSMContext,
    user_service: UserService,
) -> None:
    """Рассылает сохранённый текст всем активным пользователям.

    Список адресатов берётся заново в момент подтверждения: между шагами
    опроса могли зарегистрироваться новые покупатели.
    """
    data = await state.get_data()
    await state.clear()
    if not callback_data.approved:
        await safe_edit(
            callback.message,
            translate("admin.cancelled", language),
            admin_menu_keyboard(language),
        )
        await callback.answer()
        return
    text = (data.get("text") or "").strip()
    if not text:
        await safe_edit(
            callback.message,
            translate("common.keyboard_dismissed", language),
            admin_menu_keyboard(language),
        )
        await callback.answer()
        return
    recipients = await user_service.active_user_ids()
    delivered = await send_broadcast(bot, recipients=recipients, text=text)
    await safe_edit(
        callback.message,
        translate(
            "admin.broadcast_done",
            language,
            delivered=delivered,
            total=len(recipients),
        ),
        admin_menu_keyboard(language),
    )
    await callback.answer()


async def send_broadcast(
    bot: Bot,
    *,
    recipients: list[int],
    text: str,
) -> int:
    """Отправляет текст адресатам, возвращает число доставленных.

    Продолжает после первой ошибки: один заблокировавший бота
    пользователь не должен обрывать рассылку остальным.
    """
    delivered = 0
    for chat_id in recipients:
        try:
            await bot.send_message(chat_id, text)
            delivered += 1
        except TelegramForbiddenError:
            logger.info("Пользователь %s заблокировал бота", chat_id)
        except TelegramAPIError as error:
            logger.warning("Рассылка %s не удалась: %s", chat_id, error)
    return delivered


def admin_product_text(product: Product, language: str) -> str:
    """Текст админской карточки товара: цена и статус продажи."""
    state = translate(
        "admin.state_active" if product.is_active else "admin.state_hidden",
        language,
    )
    return (
        f"{product.title}\n"
        f"{format_price(product.price_kopecks, product.currency)} — {state}\n"
        f"slug: {product.slug}"
    )
