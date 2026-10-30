# Внешние контракты

Два внешних API: Telegram Bot API (транспорт) и YooKassa API v3 (деньги).
Всё остальное — внутренние контракты пакетов, описаны в конце.

## Telegram Bot API

Бот работает на **long-polling** (`Dispatcher.start_polling`), webhook для
Telegram не поднимается. Права бота: только отправка/правка сообщений в
личных чатах.

Используемые методы (через aiogram 3.x):

| Метод | Где | Назначение |
|-------|-----|-----------|
| `sendMessage` | `Message.answer`, `bot.send_message`, ответ троттлинга | Приветствие, каталог, карточка, выдача материалов |
| `editMessageText` | `bot/handlers/common.safe_edit` | Правка сообщения под inline-кнопками |
| `answerCallbackQuery` | `CallbackQuery.answer`, `AnswerCallbackQuery` | Ответ на нажатие, alert при доменной ошибке |
| `setMyCommands` | `bot/handlers/__init__.set_bot_commands` | Меню «/»: `BotCommandScopeDefault` + `BotCommandScopeChat` для админов |
| `sendChatAction` | `ChatActionMiddleware` | «печатает…» |

Импортозависимые лимиты, которые учитывает код:

- `callback_data` ≤ 64 байт → каждая кнопка описана моделью `CallbackData`,
  а длинные тексты срезаются `_clip` (лимит 64 символа);
- `parse_mode=HTML` задан по умолчанию в `DefaultBotProperties`, поэтому в
  текстах нельзя отдавать сырой пользовательский ввод без экранирования —
  сейчас в сообщения подставляются только названия/цены из БД;
- редактирование сообщения с идентичным текстом даёт
  `Message is not modified` — это штатная ситуация, её гасит `safe_edit`.

### Формат callback-данных

Префикс задаётся классом, дальше — поля в порядке объявления, разделитель
`:`. Пустое поле оставляет хвостовой разделитель (`adm:stats:`).

| Модель | Формат | Пример | Обработчик |
|--------|--------|--------|-----------|
| `NavCallback(prefix="nav")` | `nav:<action>` | `nav:catalog`, `nav:lang_en` | `commands.handle_language_choice`, `catalog.handle_catalog_callback`, `payment.handle_back_to_menu` |
| `ProductCallback(prefix="prod")` | `prod:<action>:<slug>` | `prod:open:kurs-po-python`, `prod:buy:...`, `prod:get_file:...`, `prod:hide/show/edit_price:...` | `catalog.handle_open_product`, `handle_get_file`, `payment.handle_buy_product`, `admin.handle_toggle_product`, `handle_edit_price_start` |
| `OrderCallback(prefix="order")` | `order:<action>:<order_id>` | `order:create_invoice:7`, `order:check_payment:7`, `order:cancel:7`, `order:repeat_delivery:7` | `payment.handle_create_invoice`, `handle_check_payment`, `handle_cancel_order`, `handle_repeat_delivery` |
| `PageCallback(prefix="page")` | `page:<action>:<page>` | `page:next:2`, `page:noop:1` | `catalog.handle_catalog_page` |
| `AdminCallback(prefix="adm")` | `adm:<action>[:<payload>]` | `adm:products:`, `adm:stats:`, `adm:edit:<slug>` | `admin.handle_admin_products`, `handle_admin_stats`, `handle_admin_edit_product` |
| `ConfirmChoiceCallback(prefix="cfm")` | `cfm:<target>:<approved>[:<payload>]` | `cfm:create_product:1:` | `admin.handle_confirm_create_product`, `handle_broadcast_confirm` |

`approved` — `bool`, кодируется как `1`/`0`. Значения `action`:

- `nav`: `catalog`, `my_purchases`, `help`, `back_menu`, `lang_ru`, `lang_en`;
- `prod`: `open`, `buy`, `get_file`, `hide`, `show`, `edit_price`;
- `order`: `create_invoice`, `check_payment`, `cancel`, `repeat_delivery`;
- `page`: `prev`, `next`, `noop` (индикатор страницы, не действие);
- `adm`: `products`, `add_product`, `broadcast`, `stats`, `edit`;
- `cfm` targets: `create_product`, `broadcast`.

Битые или чужие данные не доходят до логики: `X.filter(...)` валидирует
строку через pydantic и не пропускает хендлер при ошибке разбора.

### Deep-link

`https://t.me/<bot>?start=product:<slug>` → `handle_start_product`
(фильтр `CommandStart(magic=F.args.startswith("product:"))`).

## YooKassa API v3

Клиент — `bot/services/yookassa_client.py`. Бизнес-решений здесь нет: только
формат запроса, разбор ответа и повторы.

- База: `https://api.yookassa.ru/v3` (переопределяется `base_url` — для
  тестов).
- Авторизация: HTTP Basic, `shop_id:secret_key`. Заголовок собирается через
  `aiohttp.encode_basic_auth()` — сам `aiohttp.BasicAuth` объявлен
  устаревшим в aiohttp 3.14 и удалён будет в 4.0.
- Таймаут одного запроса: 15 с (`DEFAULT_TIMEOUT_SECONDS`).
- Повторы: до 3 попыток (`MAX_RETRY_COUNT`), линейный backoff
  `1.5 * попытка` секунды; повторяются только сетевые сбои и коды
  `429, 500, 502, 503, 504`. На остальные 4xx — сразу
  `PaymentProviderError(status_code=...)`.
- Ответ, не являющийся JSON объектом, — тоже `PaymentProviderError`.

### POST /v3/payments (создание счёта)

```json
{
  "amount": {"value": "1990.00", "currency": "RUB"},
  "capture": true,
  "confirmation": {"type": "redirect", "return_url": "https://.../done"},
  "description": "Заказ N123: Курс по Python",
  "metadata": {"order_id": "123", "user_id": "12345"}
}
```

| Параметр | Источник | Правило |
|----------|----------|---------|
| `amount.value` | `kopecks_to_str(total_kopecks)` | Строка с двумя знаками — формат обязательный |
| `amount.currency` | `orders.currency` | |
| `confirmation.return_url` | `PUBLIC_BASE_URL` из `.env` | Куда провайдер вернёт покупателя |
| `description` | `PaymentService._describe` | Обрезка до 128 символов (лимит API) |
| `metadata` | order/user | Вернётся в уведомлении, позволяет соотнести платёж |
| `Idempotence-Key` | `str(payment.id)` | Повтор после таймаута не создаёт второй счёт |

### GET /v3/payments/{id}

Используется кнопкой «Проверить оплату», чтобы не зависеть от доставки
уведомлений. Ожидается те же поля `id` / `status` / `confirmation`.

### Маппинг статусов

| YooKassa | `PaymentStatus` |
|----------|-----------------|
| `pending` | `pending` |
| `waiting_for_capture` | `processing` |
| `processing` | `processing` |
| `succeeded` | `succeeded` |
| `canceled` | `canceled` |

Неизвестный статус — `UnknownPaymentStatusError` (дочерняя
`PaymentProviderError`): молча маппить на `pending` опасно, можно выдать
неоплаченный товар.

### Уведомления (webhook) — статус на сегодня

`PaymentService.handle_provider_event(provider_payment_id, raw_status,
raw_response)` реализован и идемпотентен: на повтор уведомления он вернёт
пустой список, потому что `_settle_order` не сможет перевести уже `paid`
заказ. HTTP-эндпоинт под него **не поднят** — в текущей сборке единственный
путь подтверждения оплаты это `sync_payment_status` по кнопке. При подключении
вебхука нужен отдельный роутер/Asgi-сервер, проверка подписи
`Ipp-Secret-Key-*` и быстрый ответ `200` без бизнес-логики.

## Внутренние контракты

### Контекст обработчика (middleware → handler)

`DbSessionMiddleware` кладёт в `data`:

| Ключ | Тип |
|------|-----|
| `session` | `AsyncSession` |
| `users`, `products`, `orders`, `payments`, `purchases` | репозитории |
| `user_service` | `UserService` |
| `product_service` | `ProductService` |
| `payment_service` | `PaymentService` |

`AuthMiddleware` добавляет `tg_id: int` и `profile: UserProfile`;
`I18nMiddleware` — `language: str`. Хендлеры объявляют нужные параметры по
именам — так контракт виден в сигнатуре функции.

### Публичные API сервисов

| Сервис | Методы | Возврат |
|--------|--------|---------|
| `UserService` | `register`, `set_language`, `get_profile`, `to_profile`, `require_admin`, `active_user_ids`, `count_active` | `User` / `UserProfile` / списки ID |
| `ProductService` | `list_catalog`, `get_for_purchase`, `require_not_owned`, `get_file_url_for_owner`, `create_product`, `set_active`, `update_price`, `list_all`, `get_any`, `list_purchases`, `count_active`, `parse_price` | `ProductCard`, `PurchaseInfo`, `Product`, `int` |
| `PaymentService` | `start_checkout`, `create_payment`, `sync_payment_status`, `handle_provider_event`, `cancel_order`, `delivery_items`, `mark_delivered`, `pending_purchases`, `count_stats` | `Checkout`, `PaymentLink`, `bool`, `list[DeliveryItem]`, `tuple[int, int]` |

Деньги между слоями передаются только в копейках; строковый формат
`"1990.00"` возникает исключительно в клиенте YooKassa.

### Доменные ошибки

Все наследники `ServiceError` несут `message` (в лог) и `user_message`
(безопасный текст пользователю). Их бросают сервисы, превращает в ответ
чата `bot/handlers/errors.handle_service_error`.

| Ошибка | Причина |
|--------|---------|
| `UserNotFoundError` | Профиль не создан (событие без авторизации) |
| `ProductUnavailableError` | Товара нет или он снят с продажи |
| `AlreadyPurchasedError` | Товар уже куплен |
| `NotPurchasedError` | Запрос файла без покупки |
| `OrderNotFoundError` | Заказ не найден или чужой |
| `OrderStateError` | Переход статуса запрещён |
| `PaymentNotFoundError` | Уведомление о неизвестном счёте |
| `PaymentProviderError` | Провайдер отклонил запрос / ответил некорректно |
| `PaymentFailedError` | Платёж не завершён |
| `PermissionDeniedError` | Нет прав администратора |

`InvalidAmountError` — исключение `ValueError` из `bot/services/money.py`,
не `ServiceError`: это ошибка ввода, и хендлеры обрабатывают её отдельным
сообщением («не понимаю цену»).
