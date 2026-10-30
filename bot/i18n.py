"""Локализация текстов бота (ru/en).

Проект для СНГ, поэтому по умолчанию русский; английский подключается
флагом ``BOT_LANGUAGE_MODE=all`` и выбором пользователя в ``/start``.

Тексты живут словарём, а не в коде хендлеров: так переводы не
расползаются по обработчикам и их видно целиком. Подстановка значений
через ``str.format`` — аккуратный аналог f-строк для шаблонов.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import get_settings

RUSSIAN = "ru"
ENGLISH = "en"
SUPPORTED_LANGUAGES = (RUSSIAN, ENGLISH)
"""Языки, для которых есть полный набор строк."""


@dataclass(frozen=True)
class LocalizedText:
    """Набор строк на одном языке.

    Используется как обычный ``dict``: доступ по ключу строки, а тип
    frozen мешает случайно изменить перевод в рантайме.
    """

    data: dict[str, str]

    def get(self, key: str, language: str = RUSSIAN) -> str:
        """Возвращает строку по ключу с откатом на русский."""
        return self.data.get(key) or key


RU: dict[str, str] = {
    # --- Общие / команды ---
    "cmd.start": "👋 Привет, {name}!\n\n"
    "Я бот магазина цифровых товаров: курсы, шаблоны и чек-листы.\n"
    "Выберите действие.",
    "cmd.help": "ℹ️ Как пользоваться магазином\n\n"
    "• Каталог — покажу все товары\n"
    "• Мои покупки — доступ к купленным материалам\n"
    "• Оплата проходит через YooKassa, ссылку на оплату выдаёт бот\n\n"
    "Есть вопрос? Напишите администратору через /help в меню.",
    "cmd.catalog_empty": "Товаров пока нет — загляните позже.",
    "cmd.not_registered": "Сначала нажмите /start.",
    "cmd.unknown": "Не понимаю команду. Доступно: /start, /help, /catalog.",
    "cmd.desc.start": "Начать",
    "cmd.desc.catalog": "Каталог товаров",
    "cmd.desc.purchases": "Мои покупки",
    "cmd.desc.help": "Помощь",
    "cmd.desc.language": "Сменить язык",
    "cmd.desc.cancel": "Отменить текущий шаг",
    "cmd.desc.admin": "Админ-меню",
    "cmd.desc.products": "Список товаров",
    "cmd.desc.add_product": "Добавить товар",
    "cmd.desc.broadcast": "Рассылка всем",
    "menu.catalog": "🛍 Каталог",
    "menu.my_purchases": "📦 Мои покупки",
    "menu.help": "ℹ️ Помощь",
    "menu.back": "⬅️ Назад",
    "menu.language": "🌐 Язык",
    # --- Карточка товара и покупка ---
    "product.title": "📄 {title}",
    "product.price": "💰 Цена: {price}",
    "product.buy": "Купить",
    "product.get_file": "📥 Скачать материалы",
    "product.already_bought": "✅ Этот товар уже у вас в «Мои покупки».",
    "product.unavailable": "Товар недоступен. Выберите другой в каталоге.",
    "product.checkout_title": "🧾 Оформление заказа",
    "product.checkout_body": "Товар: {title}\nК оплате: {price}\n\n"
    "Нажмите «Создать счёт», чтобы получить ссылку на оплату.",
    "product.order_created": "📄 Заказ №{order_id} создан.\n\n"
    "Товар: {title}\nСумма: {price}",
    # --- Оплата ---
    "pay.invoice_created": "💳 Счёт создан на {price}.\n\n"
    "Нажмите кнопку «Оплатить» и завершите платёж на странице YooKassa. "
    "После возврата нажмите «Проверить оплату».",
    "pay.create_invoice": "💳 Создать счёт",
    "pay.button": "💳 Оплатить",
    "pay.check": "🔄 Проверить оплату",
    "pay.cancel": "❌ Отменить заказ",
    "pay.success": "🎉 Оплата прошла! Спасибо за покупку.",
    "pay.pending": "⏳ Платёж ещё не завершён. Попробуйте «Проверить оплату» "
    "через минуту.",
    "pay.failed": "😔 Оплата не прошла: {reason}",
    "pay.canceled": "❌ Заказ №{order_id} отменён.",
    "pay.unavailable": "Платёжная система временно недоступна. Попробуйте "
    "чуть позже.",
    "pay.order_not_found": "Заказ не найден. Оформите покупку заново.",
    "pay.already_paid": "Этот заказ уже оплачен.",
    "pay.purchases_empty": "Материалы уже выданы ранее.",
    "delivery.header": "📦 Материалы по заказу №{order_id}",
    "delivery.item": "{index}. {title}",
    "delivery.file": "📎 {title}",
    "delivery.failed": "Не удалось отправить файл. Нажмите «Повторить выдачу».",
    "delivery.retry": "🔁 Повторить выдачу",
    # --- История покупок ---
    "purchases.empty": "Покупок пока нет. Загляните в каталог!",
    "purchases.header": "📦 Ваши покупки ({count})",
    "purchases.item": "• {title} — {price}",
    # --- Админ ---
    "admin.only": "⛔️ Команда доступна только администраторам.",
    "admin.menu": "🛠 Админ-меню\n\n"
    "• /products — список товаров\n"
    "• /add_product — добавить товар\n"
    "• /broadcast — рассылка\n"
    "• /cancel — отменить текущий шаг",
    "admin.stats": "📊 Сводка\n"
    "Пользователей: {users}\n"
    "Товаров в продаже: {products}\n"
    "Оплаченных заказов: {orders}\n"
    "Выручка: {revenue}",
    "admin.products_header": "🗂 Товары ({count})",
    "admin.product_row": "{index}. {title} — {price}{marker}",
    "admin.product_hidden": " (скрыт)",
    "admin.add_product": "➕ Добавить товар",
    "admin.ask_title": "Введите название товара.",
    "admin.ask_description": "Введите описание товара.",
    "admin.ask_price": "Введите цену, например 1990 или 1990,50.",
    "admin.ask_file_url": "Введите ссылку на файл товара.",
    "admin.bad_price": "Не понимаю цену. Нужно число, например 1990 или "
    "1990,50.",
    "admin.confirm_create": "Создать товар?\n\n"
    "Название: {title}\nЦена: {price}\nСсылка: {file_url}",
    "admin.created": "✅ Товар «{title}» создан (slug: {slug}).",
    "admin.cancelled": "Отменено.",
    "admin.ask_broadcast": "Пришлите текст рассылки. Отмена — /cancel.",
    "admin.broadcast_confirm": "Отправить сообщение {count} пользователям?",
    "admin.broadcast_done": "📣 Рассылка завершена: доставлено {delivered} из "
    "{total}.",
    "admin.ask_toggle": "Что сделать с товаром «{title}»?",
    "admin.toggle_on": "🙈 Скрыть",
    "admin.toggle_off": "👁 Показать",
    "admin.toggled": "Товар «{title}» теперь {state}.",
    "admin.state_active": "в продаже",
    "admin.state_hidden": "скрыт",
    "admin.ask_new_price": "Введите новую цену для «{title}» (сейчас {price}).",
    "admin.price_updated": "Цена «{title}» обновлена: {price}.",
    # --- FSM / служебное ---
    "fsm.cancel": "Диалог прерван, вернёмся в меню.",
    "fsm.busy": "У вас уже идёт оформление. Завершите или отмените его.",
    "fsm.too_fast": "Слишком часто. Подождите {seconds} сек.",
    "common.error": "Что-то пошло не так. Попробуйте ещё раз.",
    "common.keyboard_dismissed": "Кнопки устарели — обновите список.",
}

EN: dict[str, str] = {
    "cmd.start": "👋 Hi, {name}!\n\n"
    "This is a digital goods store: courses, templates, checklists.\n"
    "Choose an action below.",
    "cmd.help": "ℹ️ How it works\n\n"
    "• Catalog — all products\n"
    "• My purchases — access to what you bought\n"
    "• Payments go through YooKassa; the bot sends a payment link",
    "cmd.catalog_empty": "No products yet — please check back later.",
    "cmd.not_registered": "Please press /start first.",
    "cmd.unknown": "Unknown command. Try /start, /help, /catalog.",
    "cmd.desc.start": "Start",
    "cmd.desc.catalog": "Catalog",
    "cmd.desc.purchases": "My purchases",
    "cmd.desc.help": "Help",
    "cmd.desc.language": "Change language",
    "cmd.desc.cancel": "Cancel current step",
    "cmd.desc.admin": "Admin menu",
    "cmd.desc.products": "Product list",
    "cmd.desc.add_product": "Add product",
    "cmd.desc.broadcast": "Broadcast to all",
    "menu.catalog": "🛍 Catalog",
    "menu.my_purchases": "📦 My purchases",
    "menu.help": "ℹ️ Help",
    "menu.back": "⬅️ Back",
    "menu.language": "🌐 Language",
    "product.title": "📄 {title}",
    "product.price": "💰 Price: {price}",
    "product.buy": "Buy",
    "product.get_file": "📥 Download files",
    "product.already_bought": "✅ You already own this item.",
    "product.unavailable": "This item is unavailable.",
    "product.checkout_title": "🧾 Checkout",
    "product.checkout_body": "Item: {title}\nTotal: {price}\n\n"
    "Press «Create invoice» to get the payment link.",
    "product.order_created": "📄 Order #{order_id} created.\n\n"
    "Item: {title}\nTotal: {price}",
    "pay.invoice_created": "💳 Invoice for {price} created.\n\n"
    "Press «Pay» and finish the payment, then use «Check payment».",
    "pay.button": "💳 Pay",
    "pay.check": "🔄 Check payment",
    "pay.cancel": "❌ Cancel order",
    "pay.success": "🎉 Payment received. Thank you!",
    "pay.pending": "⏳ Payment is not completed yet. Try «Check payment» "
    "in a minute.",
    "pay.failed": "😔 Payment failed: {reason}",
    "pay.canceled": "❌ Order #{order_id} cancelled.",
    "pay.unavailable": "Payment system is temporarily unavailable.",
    "pay.order_not_found": "Order not found. Please start over.",
    "pay.already_paid": "This order is already paid.",
    "pay.purchases_empty": "Files were already delivered.",
    "delivery.header": "📦 Files for order #{order_id}",
    "delivery.item": "{index}. {title}",
    "delivery.file": "📎 {title}",
    "delivery.failed": "Could not send the file. Press «Retry delivery».",
    "delivery.retry": "🔁 Retry delivery",
    "purchases.empty": "No purchases yet. Visit the catalog!",
    "purchases.header": "📦 Your purchases ({count})",
    "purchases.item": "• {title} — {price}",
    "admin.only": "⛔️ Admins only.",
    "admin.menu": "🛠 Admin menu\n\n"
    "• /products — product list\n"
    "• /add_product — add a product\n"
    "• /broadcast — broadcast\n"
    "• /cancel — cancel current step",
    "admin.stats": "📊 Summary\n"
    "Users: {users}\n"
    "Active products: {products}\n"
    "Paid orders: {orders}\n"
    "Revenue: {revenue}",
    "admin.products_header": "🗂 Products ({count})",
    "admin.product_row": "{index}. {title} — {price}{marker}",
    "admin.product_hidden": " (hidden)",
    "admin.add_product": "➕ Add product",
    "admin.ask_title": "Enter the product title.",
    "admin.ask_description": "Enter the product description.",
    "admin.ask_price": "Enter the price, e.g. 1990 or 1990.50.",
    "admin.ask_file_url": "Enter the file URL.",
    "admin.bad_price": "I don't understand that price. Use a number.",
    "admin.confirm_create": "Create this product?\n\n"
    "Title: {title}\nPrice: {price}\nURL: {file_url}",
    "admin.created": "✅ Product «{title}» created (slug: {slug}).",
    "admin.cancelled": "Cancelled.",
    "admin.ask_broadcast": "Send the broadcast text. /cancel to abort.",
    "admin.broadcast_confirm": "Send this message to {count} users?",
    "admin.broadcast_done": "📣 Broadcast done: {delivered} of {total} sent.",
    "admin.ask_toggle": "What to do with «{title}»?",
    "admin.toggle_on": "🙈 Hide",
    "admin.toggle_off": "👁 Show",
    "admin.toggled": "Product «{title}» is now {state}.",
    "admin.state_active": "on sale",
    "admin.state_hidden": "hidden",
    "admin.ask_new_price": "Enter the new price for «{title}» (now {price}).",
    "admin.price_updated": "Price of «{title}» is now {price}.",
    "fsm.cancel": "Dialog cancelled, back to the menu.",
    "fsm.busy": "You already have a checkout in progress.",
    "fsm.too_fast": "Too fast. Wait {seconds} seconds.",
    "common.error": "Something went wrong. Please try again.",
    "common.keyboard_dismissed": "Buttons are outdated — refresh the list.",
}

_CATALOGS: dict[str, dict[str, str]] = {RUSSIAN: RU, ENGLISH: EN}


def _client_language(
    telegram_language: str | None,
    supported: tuple[str, ...],
) -> str | None:
    """Сопоставляет ``language_code`` Telegram с поддерживаемыми языками.

    Telegram присылает локаль целиком (``en-US``, ``pt_BR``), а словари
    ключей — двухбуквенные коды, поэтому сравнивается только префикс
    языка.
    """
    if not telegram_language:
        return None
    base = telegram_language.lower().replace("_", "-").split("-")[0]
    return base if base in supported else None


def available_languages() -> tuple[str, ...]:
    """Языки, разрешённые конфигурацией.

    Returns:
        ``("ru",)`` при ``BOT_LANGUAGE_MODE=ru`` и ``("ru", "en")``
        при ``all``.
    """
    mode = get_settings().bot_language_mode
    if mode == "all":
        return SUPPORTED_LANGUAGES
    return (mode,)


def resolve_language(
    telegram_language: str | None,
    saved_language: str | None = None,
) -> str:
    """Выбирает язык пользователя.

    Приоритет: явно сохранённый выбор > язык клиента Telegram (если он
    поддерживается) > язык из конфига.

    Args:
        telegram_language: ``language_code`` из профиля Telegram.
        saved_language: Язык, который пользователь выбрал в боте.

    Returns:
        Код языка из :data:`SUPPORTED_LANGUAGES`.
    """
    supported = available_languages()
    if saved_language in supported:
        return saved_language  # type: ignore[return-value]
    client = _client_language(telegram_language, supported)
    if client:
        return client
    default = get_settings().default_language
    return default if default in supported else supported[0]


def translate(key: str, language: str, **params: object) -> str:
    """Возвращает локализованную строку с подстановкой значений.

    Args:
        key: Ключ строки (см. словари выше).
        language: Код языка; при отсутствии строки берётся русский.
        **params: Аргументы для ``str.format``.

    Returns:
        Готовый текст. Если ключа нет — сам ключ: в интерфейсе это
        заметно сразу, а не выглядит как пустое сообщение.
    """
    catalog = _CATALOGS.get(language, RU)
    template = catalog.get(key) or RU.get(key) or key
    if not params:
        return template
    try:
        return template.format(**params)
    except KeyError:
        # Не хватает аргумента: лучше показать шаблон, чем уронить ответ бота.
        return template


def t(key: str, language: str | None = None, **params: object) -> str:
    """Сокращённый доступ к :func:`translate` (язык по умолчанию)."""
    return translate(key, language or get_settings().default_language, **params)
