"""Inline-клавиатуры бота.

Все кнопки создаются здесь: хендлеры только вызывают функции и вставляют
результат в ``reply_markup``. Это сохраняет тексты и callback-данные в
одном месте и позволяет держать единый набор кнопок для ru/en.

Reply-меню под полем ввода — в :mod:`bot.keyboards.reply`.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import RUSSIAN, available_languages, translate
from bot.keyboards.callback_data import (
    AdminCallback,
    ConfirmChoiceCallback,
    NavCallback,
    OrderCallback,
    PageCallback,
    ProductCallback,
)
from bot.services.product_service import ProductCard

CATALOG_PAGE_SIZE = 5
"""Товаров на одной странице каталога."""

MAX_BUTTON_TEXT = 64
"""Лимит длины текста кнопки в Telegram."""


def _clip(text: str, limit: int = MAX_BUTTON_TEXT) -> str:
    """Срезает текст до лимита Telegram, добавляя многоточие."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def language_keyboard(language: str = RUSSIAN) -> InlineKeyboardMarkup:
    """Выбор языка интерфейса (виден только при ``BOT_LANGUAGE_MODE=all``)."""
    builder = InlineKeyboardBuilder()
    for code in available_languages():
        label = "🇷🇺 Русский" if code == "ru" else "🇬🇧 English"
        marker = "✓ " if code == language else ""
        builder.button(
            text=f"{marker}{label}",
            callback_data=NavCallback(action=f"lang_{code}"),
        )
    builder.adjust(1)
    return builder.as_markup()


def catalog_keyboard(
    products: list[ProductCard],
    language: str = RUSSIAN,
    page: int = 0,
) -> InlineKeyboardMarkup:
    """Список товаров постранично.

    Ряды собираются вручную, а не через ``builder.adjust()``: ``adjust``
    пересобирает все кнопки в плоский список и уничтожил бы строку
    навигации, где три кнопки должны стоять рядом.

    Args:
        products: Полная выборка активных товаров.
        language: Код языка.
        page: Номер страницы (0-based).

    Returns:
        Inline-клавиатуру с товарами текущей страницы и стрелками.
    """
    rows: list[list[InlineKeyboardButton]] = []
    start = page * CATALOG_PAGE_SIZE
    for card in products[start : start + CATALOG_PAGE_SIZE]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_clip(f"{card.title} — {card.formatted_price}"),
                    callback_data=ProductCallback(
                        action="open", slug=card.slug
                    ).pack(),
                )
            ]
        )

    total_pages = (len(products) + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=PageCallback(
                        action="prev", page=page - 1
                    ).pack(),
                )
            )
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data=PageCallback(action="noop", page=page).pack(),
            )
        )
        if page + 1 < total_pages:
            nav.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=PageCallback(
                        action="next", page=page + 1
                    ).pack(),
                )
            )
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(
                text=translate("menu.back", language),
                callback_data=NavCallback(action="back_menu").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_keyboard(
    card: ProductCard,
    language: str = RUSSIAN,
    *,
    owned: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки карточки товара: купить или скачать, если уже куплено."""
    builder = InlineKeyboardBuilder()
    if owned:
        builder.button(
            text=translate("product.get_file", language),
            callback_data=ProductCallback(action="get_file", slug=card.slug),
        )
    else:
        builder.button(
            text=translate("product.buy", language),
            callback_data=ProductCallback(action="buy", slug=card.slug),
        )
    builder.button(
        text=translate("menu.back", language),
        callback_data=NavCallback(action="catalog"),
    )
    builder.adjust(1)
    return builder.as_markup()


def checkout_keyboard(
    order_id: int,
    language: str = RUSSIAN,
    *,
    show_payment: bool = True,
    confirmation_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Кнопки заказа: ссылка на оплату, проверка, отмена."""
    builder = InlineKeyboardBuilder()
    if show_payment and confirmation_url:
        builder.button(
            text=translate("pay.button", language),
            url=confirmation_url,
        )
    builder.button(
        text=translate("pay.check", language),
        callback_data=OrderCallback(action="check_payment", order_id=order_id),
    )
    builder.button(
        text=translate("pay.cancel", language),
        callback_data=OrderCallback(action="cancel", order_id=order_id),
    )
    builder.button(
        text=translate("menu.catalog", language),
        callback_data=NavCallback(action="catalog"),
    )
    builder.adjust(1)
    return builder.as_markup()


def checkout_confirm_keyboard(
    order_id: int,
    language: str = RUSSIAN,
) -> InlineKeyboardMarkup:
    """Подтверждение оформления: создать счёт или отказаться.

    Отдельная клавиатура, а не ``checkout_keyboard``, потому что до
    создания счёта в YooKassa кнопки «Оплатить» и «Проверить оплату»
    бессмысленны — пользователю нужно именно подтвердить заказ.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=translate("pay.create_invoice", language),
        callback_data=OrderCallback(action="create_invoice", order_id=order_id),
    )
    builder.button(
        text=translate("pay.cancel", language),
        callback_data=OrderCallback(action="cancel", order_id=order_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def delivery_keyboard(
    file_url: str,
    language: str = RUSSIAN,
) -> InlineKeyboardMarkup:
    """Ссылка на материалы купленного товара."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_clip(translate("product.get_file", language)),
        url=file_url,
    )
    builder.button(
        text=translate("menu.catalog", language),
        callback_data=NavCallback(action="catalog"),
    )
    builder.adjust(1)
    return builder.as_markup()


def purchase_keyboard(
    slug: str,
    language: str = RUSSIAN,
    *,
    order_id: int | None = None,
) -> InlineKeyboardMarkup:
    """Кнопки истории покупки: снова скачать материалы."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=translate("product.get_file", language),
        callback_data=ProductCallback(action="get_file", slug=slug),
    )
    if order_id is not None:
        builder.button(
            text=translate("delivery.retry", language),
            callback_data=OrderCallback(
                action="repeat_delivery", order_id=order_id
            ),
        )
    builder.button(
        text=translate("menu.catalog", language),
        callback_data=NavCallback(action="catalog"),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_products_keyboard(
    products: list[ProductCard],
    language: str = RUSSIAN,
) -> InlineKeyboardMarkup:
    """Админский список товаров: выбрать для редактирования."""
    builder = InlineKeyboardBuilder()
    for card in products:
        builder.button(
            text=_clip(f"{card.title} — {card.formatted_price}"),
            callback_data=AdminCallback(action="edit", payload=card.slug),
        )
    builder.button(
        text=translate("admin.add_product", language),
        callback_data=AdminCallback(action="add_product"),
    )
    builder.button(
        text=translate("menu.back", language),
        callback_data=NavCallback(action="back_menu"),
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_menu_keyboard(language: str = RUSSIAN) -> InlineKeyboardMarkup:
    """Главное админ-меню."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗂 Товары",
        callback_data=AdminCallback(action="products"),
    )
    builder.button(
        text=translate("admin.add_product", language),
        callback_data=AdminCallback(action="add_product"),
    )
    builder.button(
        text="📣 Рассылка",
        callback_data=AdminCallback(action="broadcast"),
    )
    builder.button(
        text="📊 Статистика",
        callback_data=AdminCallback(action="stats"),
    )
    builder.adjust(2)
    return builder.as_markup()


def confirm_keyboard(
    target: str,
    payload: str = "",
    language: str = RUSSIAN,
) -> InlineKeyboardMarkup:
    """Подтверждение/отмена действия (создание товара, рассылка)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да",
        callback_data=ConfirmChoiceCallback(
            target=target, approved=True, payload=payload
        ),
    )
    builder.button(
        text="❌ Нет",
        callback_data=ConfirmChoiceCallback(
            target=target, approved=False, payload=payload
        ),
    )
    builder.adjust(2)
    return builder.as_markup()


def toggle_keyboard(
    slug: str,
    language: str = RUSSIAN,
    *,
    is_active: bool,
) -> InlineKeyboardMarkup:
    """Кнопки редактирования товара: скрыть/показать, цена, назад."""
    builder = InlineKeyboardBuilder()
    action = "hide" if is_active else "show"
    label = translate(
        "admin.toggle_on" if is_active else "admin.toggle_off", language
    )
    builder.button(
        text=label,
        callback_data=ProductCallback(action=action, slug=slug),
    )
    builder.button(
        text="💰 Цена",
        callback_data=ProductCallback(action="edit_price", slug=slug),
    )
    builder.button(
        text=translate("menu.back", language),
        callback_data=AdminCallback(action="products"),
    )
    builder.adjust(1)
    return builder.as_markup()
