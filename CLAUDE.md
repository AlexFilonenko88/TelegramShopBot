# CLAUDE.md — Инструкции для Claude Code

## Проект
TelegramShopBot — Telegram-бот для продажи цифровых товаров (курсы, шаблоны, чек-листы).
Целевая аудитория: малый бизнес и фрилансеры в СНГ.

## Технологический стек
- **Язык:** Python 3.14
- **Telegram-библиотека:** aiogram 3.x (НЕ aiogram 2.x — они несовместимы!)
- **Виртуальное окружение:** .venv
- **База данных:** PostgreSQL 15 + SQLAlchemy 2.0 (async)
- **Миграции:** Alembic
- **Платёжная система:** YooKassa API v3 (aiohttp, свой клиент в `bot/services/yookassa_client.py`)
- **Переменные окружения:** pydantic-settings читает `.env` напрямую (python-dotenv не используется); файл не коммитить!
- **HTTP-транспорт к Telegram:** aiogram 3.x на aiohttp, long-polling (webhook не поднят)
- **Зависимости:** pyproject.toml + poetry (НЕ requirements.txt)
- **Тесты:** pytest + pytest-asyncio (`asyncio_mode = auto`), marker `integration`
- **Запуск:** Docker Compose

## Структура проекта
```
TelegramShopBot/
├── bot/
│   ├── handlers/       # Обработчики команд и callback-ов
│   ├── keyboards/      # Inline и Reply клавиатуры
│   ├── middlewares/    # Middleware (auth, throttling, i18n)
│   ├── services/       # Бизнес-логика (payment, products, users)
│   └── states/         # FSM состояния
├── db/
│   ├── models/         # SQLAlchemy модели
│   ├── repositories/   # Паттерн Repository (CRUD)
│   └── migrations/     # Alembic миграции
|
├── tests/              # Тесты
├── docs/               # Документация
├── .env                # Переменные окружения
├── config.py           # Конфиг из .env (НЕ ТРОГАТЬ!)
├── main.py             # Точка входа
├── docker-compose.yml
└── pyproject.toml
```

## Соглашения по коду
- Все файлы: snake_case (user_service.py, not UserService.py)
- Классы: PascalCase (ProductRepository, PaymentService)
- Константы: UPPER_SNAKE_CASE (MAX_RETRY_COUNT = 3)
- Обработчики: префикс handle_ (handle_start, handle_buy_product)
- Сервисы: суффикс Service (PaymentService, UserService)
- Репозитории: суффикс Repository (ProductRepository)

## Как работать с БД
- ВСЕГДА использовать async/await (мы на asyncpg)
- Паттерн Repository: логика запросов только в db/repositories/
- В handlers только вызовы сервисов, не прямые запросы к БД
- Сессия передаётся через middleware, не создаётся вручную

## Что НЕЛЬЗЯ делать
- ❌ НЕ трогать config.py — конфиг настроен, там хитрая валидация
- ❌ НЕ использовать aiogram 2.x синтаксис (Dispatcher, executor)
- ❌ НЕ хранить секреты в коде — только в .env
- ❌ НЕ писать прямые SQL запросы — только через SQLAlchemy ORM
- ❌ НЕ удалять файлы миграций — только добавлять новые
- ❌ НЕ использовать requirements.txt — только pyproject.toml

## Команды для работы
```bash
# Запуск проекта
docker-compose up -d

# Создание миграции
alembic revision --autogenerate -m "add products table"

# Применить миграции
alembic upgrade head

# Тесты
pytest tests/ -v

# Логи бота
docker-compose logs -f bot
```

Все команды — через окружение проекта, системный Python не используется:

```bash
.venv/bin/python -m pytest tests/ -q          # тесты
.venv/bin/python -m black bot/ db/ main.py tests/ config.py -q
.venv/bin/python -m ruff check bot/ db/ main.py tests/ config.py --output-format=concise
.venv/bin/alembic upgrade head                # схема
.venv/bin/alembic current                     # ревизия (должна быть head)
```

Эквивалент через poetry: `poetry run pytest`, `poetry run black ...`.
После любой правки кода прогонять все три проверки — black, ruff, pytest.

## Инварианты слоёв (не нарушать)
- `bot/handlers/*` — никакого SQL и никаких импортов `sqlalchemy`.
- `bot/services/*` — ничего не знает про Telegram: ни `Message`, ни
  `CallbackQuery`, ни клавиатуры. Возвращают dataclass-ы и доменные ошибки.
- `db/repositories/*` — единственное место с `select()/update()`.
- Деньги — целые копейки (`*_kopecks`), форматирование только в
  `bot/services/money.py`.
- Смена статуса заказа — только `OrderRepository.transition(from_statuses=...,
  to=...)`: атомарный `UPDATE ... WHERE status IN (...)`.
- `products.file_url` не покидает слой сервиса без проверки покупки
  (`get_file_url_for_owner`).

## Порядок middleware (main.py)
`Throttling → DbSession → Auth → I18n → ChatAction`, вешаются как **outer** на
`dispatcher.message` и `dispatcher.callback_query` — не на `update` (у `Update`
нет `from_user`, а корневые фильтры роутеров проверяются до inner-middleware).
Порядок подключения роутеров в `bot/handlers/__init__.build_routers()` — тоже
часть логики: `admin → catalog → payment → commands`.

## Подводные камни aiogram 3.x (проверено на этой версии)
- `F` и `MagicFilter` импортируются из `aiogram`; `aiogram.filters.magic` не
  существует. Работает `F.x.in_([...])`, `is_in` — нет.
- `BotCommand(command="start", description=...)` — параметр `description`, не
  `text`.
- `Command()` без списка команд запрещён; неизвестные команды ловятся
  `F.text.startswith("/") & F.command.is_(None)`.
- `CommandStart`/`Command` вычисляют `command` сами: передавать `command=` в
  `__call__` нельзя, `bot` (с `username`) обязателен.
- Собственные фильтры вызываются как callable: `await MyFilter()(event, bot=...)`;
  `.check()` есть только у `MagicData`.
- `StateFilter` читает `raw_state` — в ручных цепочках проверки его надо
  подкладывать самому.
- Сигнатура `__call__` фильтра: событие передаётся позиционно, поэтому первый
  параметр не должен называться `message`/`callback_query` и пересекаться с
  именованными аргументами (`IsAdminFilter.__call__(self, event, profile=None)`).
- `aiohttp.BasicAuth` устарел в 3.14 — авторизация через
  `aiohttp.encode_basic_auth()` + заголовок `Authorization`.
- Callback-данные без значения поля дают хвостовой разделитель:
  `adm:stats:`, `cfm:create_product:1:`; `NavCallback(action='catalog')` →
  `nav:catalog` (без хвоста).

## Тесты
Unit-тесты (деньги, i18n, клавиатуры, фильтры, троттлинг, клиент YooKassa) не
требуют ни сети, ни БД. `tests/test_repositories.py` помечен `integration` и
без PostgreSQL **пропускается**, а не падает — зелёный прогон без БД не означает,
что SQL проверен. Полный прогон требует кластер:

```bash
initdb -D /tmp/shopbot-pg -A trust -U shop_bot
pg_ctl -D /tmp/shopbot-pg -l /tmp/shopbot-pg.log \
    -o "-p 55432 -k /tmp -c listen_addresses=127.0.0.1" start
createdb -h 127.0.0.1 -p 55432 -U shop_bot shop_bot
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest tests/ -q     # 107 passed
```

`/tmp` периодически очищается — кластер пересоздаётся теми же командами.

## Документация
`docs/README.md` — индекс. Обязательное чтение перед правкой:
- `docs/architecture.md` — слои, поток сообщения, почему middleware outer;
- `docs/db_schema.md` — таблицы, индексы, enum-ы, миграции;
- `docs/api_contracts.md` — формат callback-данных, YooKassa v3, контракты сервисов;
- `docs/business_logic.md` — правила: заказ, оплата, выдача, роли, троттлинг;
- `docs/deployment.md` — compose, env, systemd, масштабирование;
- `docs/decisions.md` — ADR-001…018: почему так и что отвергнуто.
Изменение поведения или схемы требует правки соответствующего документа в том же
коммите.

## Стиль кода
- Максимальная длина строки: 80 символов
- Форматтер: black
- Линтер: ruff
- Типизация: обязательна для всех функций (type hints)
- Docstrings: для публичных методов обязательны (Google style)

## Папка docs/ как база знаний
Создана и актуальна; индекс — `docs/README.md`. Состав:

```
docs/
├── README.md            # индекс и главные инварианты
├── architecture.md      # Общая архитектура, как компоненты связаны
├── db_schema.md         # Схема БД: таблицы, поля, связи
├── api_contracts.md     # Внешние API: YooKassa, Telegram Bot API
├── business_logic.md    # Правила бизнеса: жизненный цикл заказа, права, лимиты
├── deployment.md        # Как деплоить: compose, env, systemd, nginx
└── decisions.md         # Архитектурные решения и почему так (ADR-001…018)
```
