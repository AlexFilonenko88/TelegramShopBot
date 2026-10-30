# syntax=docker/dockerfile:1
# Образ бота: только рантайм-зависимости, без dev-инструментов.

FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.1.1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# psycopg-не нужен, но libpq тянется asyncpg — оставляем минимум системных пакетов
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

# Зависимости отдельным слоем: код меняется чаще, чем lock-файл
COPY pyproject.toml poetry.lock poetry.toml ./
RUN poetry install --only main --no-interaction --no-ansi --no-root

COPY . .

# Бот работает не от root
RUN useradd --create-home --uid 1000 bot \
    && chown -R bot:bot /app
USER bot

# Проверяет, что приложение вообще импортируется: ловит сломанную сборку,
# не дёргая Telegram и не занимая соединение с БД.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import main" || exit 1

CMD ["python", "main.py"]
