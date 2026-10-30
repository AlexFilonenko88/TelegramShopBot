# Деплой

## Вариант 1 — Docker Compose (рекомендуемый)

Состав (`docker-compose.yml`): сервис `db` (`postgres:15-alpine`, том
`pgdata`) и сервис `bot` (образ из `Dockerfile`).

```bash
cp .env.example .env      # заполнить реальные значения
docker compose up -d --build
docker compose logs -f bot
```

Что происходит при старте:

1. `db` поднимается и проходит healthcheck `pg_isready`;
2. `bot` стартует только после `condition: service_healthy` — иначе
   миграции падают на гонке;
3. команда контейнера: `sh -c "alembic upgrade head && python main.py"` —
   схема накатывается автоматически, ручной шаг не забудется;
4. внутри сети compose БД доступна по хосту `db`: `DB_HOST=db`,
   `DB_PORT=5432` заданы в `environment` сервиса и перекрывают `.env`.

Переменные, обязательные для compose: `POSTGRES_PASSWORD` (пароль контейнера,
`:?` в compose не даст стартовать без него) и `DB_PASSWORD` (пароль, под которым
подключается бот) — в односервисной установке они должны совпадать.

### Образ (`Dockerfile`)

- База `python:3.14-slim`.
- `POETRY_VIRTUALENVS_CREATE=false` — зависимости в системный site-packages,
  виртуальное окружение внутри контейнера не нужно.
- `poetry install --only main` — dev-зависимости (pytest, black, ruff) в образ
  не попадают.
- `pyproject.toml`/`poetry.lock` копируются отдельным слоем: код меняется чаще
  lock-файла, поэтому слой зависимостей переиспользуется кэшем.
- Рабочий процесс под пользователем `bot` (uid 1000), не root.
- `HEALTHCHECK CMD python -c "import main"` — ловит сломанную сборку, не дёргая
  Telegram и не занимая соединение с БД.
- `.dockerignore` исключает `.venv`, `.git`, кэш, `tests/` и `.env` — секреты не
  должны попадать в слои образа.

### Обновление версии

```bash
git pull
docker compose up -d --build     # пересборка + alembic upgrade head при старте
```

Если миграция меняла данные, сначала резервная копия:

```bash
docker compose exec db pg_dump -U shop_bot shop_bot | gzip > backup.sql.gz
```

### Откат миграции

```bash
docker compose exec bot alembic downgrade -1
docker compose exec bot alembic current
```

`downgrade` начальной миграции удаляет enum-типы сырым SQL — это единственный
случай, где DROP TYPE нужен вручную; обычные миграции обязаны описывать откат
сами.

## Вариант 2 — локально без Docker

Требуется Python 3.14 и Poetry 2.x.

```bash
poetry install
poetry run alembic upgrade head
poetry run python main.py
```

Временный PostgreSQL для разработки (без системного сервиса):

```bash
initdb -D /tmp/shopbot-pg -A trust -U shop_bot
pg_ctl -D /tmp/shopbot-pg -l /tmp/shopbot-pg.log \
    -o "-p 55432 -k /tmp -c listen_addresses=127.0.0.1" start
createdb -h 127.0.0.1 -p 55432 -U shop_bot shop_bot
```

В `.env`: `DB_PORT=55432`, `DB_PASSWORD` можно оставить пустым (`-A trust`).
Остановка: `pg_ctl -D /tmp/shopbot-pg stop`.

## Вариант 3 — systemd + nginx (VPS без Docker)

Юнит `/etc/systemd/system/shopbot.service`:

```ini
[Unit]
Description=TelegramShopBot
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
User=bot
WorkingDirectory=/opt/shopbot
EnvironmentFile=/opt/shopbot/.env
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`ExecStart` добавляется отдельной строкой и оборачивает две команды в `sh -c`,
иначе миграции не будет перед стартом:

```ini
ExecStart=/bin/sh -c '.venv/bin/alembic upgrade head && .venv/bin/python main.py'
```

Логгер systemd: `journalctl -u shopbot -f`.

nginx нужен **только** если подключается webhook YooKassa или другой HTTP
эндпоинт: сам бот на long-polling входящих соединений не требует. Пример для
будущего вебхука:

```nginx
server {
    listen 443 ssl http2;
    server_name shop.example.com;
    location /payments/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Тогда же `PUBLIC_BASE_URL` в `.env` обязан стать этим HTTPS-адресом —
`ENVIRONMENT=production` не даст боту стартовать без `https://`.

## Конфигурация окружения

| Переменная | Dev | Prod |
|-----------|-----|------|
| `BOT_TOKEN` | тестовый токен | боевой, от отдельного бота |
| `ADMIN_IDS` | свой ID | рабочие ID, без личных аккаунтов |
| `DB_HOST` / `DB_PORT` | `localhost` / `55432` | `db` (compose) или managed PG |
| `DB_PASSWORD` | пусто при `trust` | обязательен, без плейсхолдеров |
| `POSTGRES_PASSWORD` | не нужен | совпадает с `DB_PASSWORD` для compose |
| `YOOKASSA_SHOP_ID` / `YOOKASSA_SECRET_KEY` | тестовые ключи ЛК | боевые; тестовые в прод не попадут — валидация не пропустит слово `test`/`replace` |
| `PUBLIC_BASE_URL` | `http://localhost:8080` | `https://<домен>` |
| `ENVIRONMENT` | `development` | `production` |
| `BOT_LANGUAGE_MODE` / `DEFAULT_LANGUAGE` | `ru` | по аудитории |
| `LOG_LEVEL` | `DEBUG`/`INFO` | `INFO` |

Строгая валидация в `production` (`config.py`, не правится): пустой
`DB_PASSWORD`, пустые ключи YooKassa, пустой `ADMIN_IDS`, `PUBLIC_BASE_URL`
без `https://` и значения-заглушки (`replace`, `changeme`, `secret`,
`example`, `your`, `xxx`) — отказ старта со списком проблем.

## Масштабирование и состояние

Бот **однопоточный по инстансу**: `MemoryStorage` для FSM и счётчики
троттлинга живут в памяти процесса, а Telegram long-polling позволяет только
одно активное соединение `getUpdates` на токен. Запускать несколько копий
`bot` с одним токеном нельзя.

Если понадобится больше одного воркера:

1. FSM → `RedisStorage` (aiogram поддерживает),
2. `RateLimiter` → Redis (логика лимита уже изолирована, менять придётся только
   хранилище),
3. webhook Telegram вместо polling + балансировщик,
4. пул соединений: `pool_size=5`, `max_overflow=10` в `db/session.py` —
   пересчитать под число воркеров и `max_connections` Postgres.

## Мониторинг

- Логи в stdout в формате `%(asctime)s [%(levelname)s] %(name)s: %(message)s`;
  `PYTHONUNBUFFERED=1` в образе, поэтому `docker logs` пишет сразу.
- Ключевые события в `INFO`/`WARNING`: создание и переходы заказов, ответы
  YooKassa, отклонённые события троттлинга, откат транзакции, сбои выдачи
  файлов, недоставленная рассылка.
- `SQLAlchemy echo` включается только при `ENVIRONMENT=development`.
- Признак зависшего long-polling — отсутствие записей у `bot` при живом
  `db`; `docker compose restart bot` помогает, т.к. состояние бота не
  сохраняется.

## Проверка после деплоя

```bash
docker compose ps                       # bot и db — running/healthy
docker compose logs --tail 50 bot       # «Бот запущен: окружение=production»
docker compose exec bot alembic current # head-ревизия
```

Затем в Telegram: `/start` → `/catalog` (товар добавлен `/add_product`) →
карточка → «Купить» → «Создать счёт» (с тестовыми ключами YooKassa платёж
проходит в тестовом режиме) → «Проверить оплату» → выдача → `/purchases`.
