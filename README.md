# TelegramShopBot

Telegram-бот для продажи цифровых товаров: каталог, оплата через
YooKassa, автоматическая выдача файлов и админка с управлением товарами.

## Стек

| Слой | Технология |
|------|-----------|
| Язык | Python 3.14 |
| Telegram | aiogram 3.x (long-polling) |
| БД | PostgreSQL 15, SQLAlchemy 2.x (async, asyncpg) |
| Миграции | Alembic |
| Платежи | YooKassa API v3 |
| Конфиг | pydantic-settings + `.env` |
| Зависимости | poetry (`pyproject.toml`) |

## Быстрый старт

### 1. Переменные окружения

```bash
cp .env.example .env
```

Заполните в `.env`:

- `BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather);
- `ADMIN_IDS` — Telegram ID администраторов через запятую (узнать свой
  можно у [@userinfobot](https://t.me/userinfobot));
- `DB_*` — параметры PostgreSQL;
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY` — из личного кабинета
  YooKassa (для тестов подойдут тестовые ключи).

`ENVIRONMENT=production` включает строгую валидацию: бот не стартует с
пустым паролем БД, заглушками вида `change-me` и `PUBLIC_BASE_URL` без
`https://`.

### 2. Запуск через Docker Compose

```bash
docker compose up -d --build
docker compose logs -f bot
```

Контейнер сам применяет миграции (`alembic upgrade head`) перед стартом
и ждёт готовности БД.

### 3. Локальный запуск

```bash
poetry install
poetry run alembic upgrade head
poetry run python main.py
```

Для локальной БД удобен временный кластер:

```bash
initdb -D /tmp/shopbot-pg -A trust -U shop_bot
pg_ctl -D /tmp/shopbot-pg -l /tmp/shopbot-pg.log \
    -o "-p 55432 -k /tmp -c listen_addresses=127.0.0.1" start
createdb -h 127.0.0.1 -p 55432 -U shop_bot shop_bot
```

В `.env` при этом укажите `DB_PORT=55432`.

## Команды

### Покупатель

| Команда | Действие |
|---------|----------|
| `/start` | Приветствие и главное меню |
| `/start product:<slug>` | Карточка товара по deep-link |
| `/catalog` | Каталог с постраничной навигацией |
| `/purchases` | История покупок и повторная выдача файлов |
| `/language` | Смена языка (если `BOT_LANGUAGE_MODE=all`) |
| `/help` | Краткая справка |
| `/cancel` | Выход из пошагового диалога |

### Администратор

| Команда | Действие |
|---------|----------|
| `/admin` | Админ-меню |
| `/products` | Список товаров, включая скрытые |
| `/add_product` | Анкета нового товара (название → описание → цена → ссылка) |
| `/broadcast` | Рассылка всем активным пользователям |

## Разработка

```bash
# форматирование и линт
poetry run black bot/ db/ main.py
poetry run ruff check bot/ db/ main.py

# тесты
poetry run pytest tests/ -v

# новая миграция
poetry run alembic revision --autogenerate -m "add something"
poetry run alembic upgrade head
```

## Структура

```
bot/
├── handlers/     # обработчики команд и callback-ов
├── keyboards/    # inline и reply клавиатуры
├── middlewares/  # throttling → db → auth → i18n
├── services/     # бизнес-логика, YooKassa
├── states/       # FSM-состояния диалогов
└── i18n.py       # тексты RU/EN
db/
├── models/       # SQLAlchemy-модели
├── repositories/ # доступ к данным
└── migrations/   # Alembic
docs/             # архитектура, схема БД, ADR
tests/            # pytest
config.py         # настройки из .env
main.py           # точка входа
```

Подробности — в [`docs/`](docs/): архитектура, схема БД, контракты
внешних API, бизнес-правила, деплой и принятые решения.

## Как проходит покупка

1. Покупатель открывает каталог и карточку товара.
2. «Купить» создаёт заказ в статусе `pending` — деньги ещё не списаны.
3. «Оплатить» создаёт счёт в YooKassa и отдаёт ссылку на оплату.
4. После оплаты товар выдаётся либо по кнопке «Проверить оплату»
   (бот опрашивает провайдера), либо по webhook-уведомлению.
5. Выдача идемпотентна: повторное нажатие или повторный webhook не
   создают вторую покупку.

Деньги везде хранятся в копейках (`price_kopecks`, `total_kopecks`):
float для сумм не используется.
