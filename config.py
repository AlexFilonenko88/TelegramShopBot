"""Конфигурация приложения.

Единственный источник настроек: файл ``.env`` (см. ``.env.example``).
Секреты не хранятся в коде. Валидация намеренно строгая: бот не должен
стартовать с неполными или плейсхолдерными значениями в production.

ВАЖНО: файл настроен и не правится без явного запроса.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from pydantic_settings import NoDecode
except ImportError:  # pragma: no cover - старые версии pydantic-settings
    NoDecode = None  # type: ignore[assignment]

Environment = Literal["development", "production"]
Language = Literal["ru", "en"]
LanguageMode = Literal["ru", "en", "all"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

BOT_TOKEN_PATTERN = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")
PLACEHOLDER_MARKERS = (
    "replace",
    "changeme",
    "change-me",
    "secret",
    "example",
    "your",
    "xxx",
)
"""Части значений-заглушек из ``.env.example``, запрещённые в production."""


class Settings(BaseSettings):
    """Настройки бота, читаемые из переменных окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: str = Field(..., repr=False)
    # NoDecode отключает встроенный JSON-парсинг сложных типов: список
    # администраторов задаётся человекочитаемо как "111,222".
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # --- PostgreSQL ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "shop_bot"
    db_user: str = "shop_bot"
    db_password: str = Field(default="", repr=False)

    # --- YooKassa ---
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = Field(default="", repr=False)
    public_base_url: str = "http://localhost:8080"

    # --- Приложение ---
    environment: Environment = "development"
    default_language: Language = "ru"
    bot_language_mode: LanguageMode = "ru"
    log_level: LogLevel = "INFO"

    @field_validator("bot_token", mode="before")
    @classmethod
    def _validate_bot_token(cls, value: Any) -> Any:
        """Проверяет формат токена, выданного @BotFather.

        Args:
            value: Исходное значение переменной окружения.

        Returns:
            Нормализованный токен.

        Raises:
            ValueError: Если токен пустой или имеет неверный формат.
        """
        if not isinstance(value, str):
            raise ValueError("BOT_TOKEN должен быть строкой")
        token = value.strip()
        if not token:
            raise ValueError("BOT_TOKEN не может быть пустым")
        if not BOT_TOKEN_PATTERN.match(token):
            raise ValueError(
                "BOT_TOKEN имеет неверный формат: ожидается "
                "'<digits>:<30+ символов>' от @BotFather"
            )
        return token

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> list[int]:
        """Разбирает список ID администраторов из строки вида '1,2 , 3'.

        Args:
            value: Строка, число или список элементов.

        Returns:
            Список положительных Telegram ID без дублей (в исходном порядке).

        Raises:
            ValueError: Если хотя бы один элемент не является числом.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return []
        raw_items = (
            value.split(",")
            if isinstance(value, str)
            else ([value] if isinstance(value, int) else list(value))
        )
        result: list[int] = []
        for item in raw_items:
            text = str(item).strip()
            if not text:
                continue
            try:
                tg_id = int(text)
            except ValueError as exc:
                raise ValueError(
                    f"ADMIN_IDS содержит не-числовое значение: {text!r}"
                ) from exc
            if tg_id <= 0:
                raise ValueError(
                    f"ADMIN_IDS: Telegram ID должен быть > 0: {tg_id}"
                )
            if tg_id not in result:
                result.append(tg_id)
        return result

    @field_validator("public_base_url", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, value: Any) -> Any:
        """Убирает завершающий слэш из базового URL."""
        if isinstance(value, str):
            return value.strip().rstrip("/")
        return value

    @field_validator("db_password", "yookassa_secret_key", "yookassa_shop_id")
    @classmethod
    def _strip_value(cls, value: str) -> str:
        """Нормализует строковые значения, срезая пробелы."""
        return value.strip()

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        """Запрещает заглушки и требует полные данные в production.

        Returns:
            Экземпляр настроек.

        Raises:
            ValueError: Если конфигурация непригодна для production.
        """
        if self.environment != "production":
            return self
        problems: list[str] = []
        if not self.db_password:
            problems.append("DB_PASSWORD не задан")
        if not self.yookassa_shop_id or not self.yookassa_secret_key:
            problems.append("YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY не заданы")
        if not self.admin_ids:
            problems.append("ADMIN_IDS пуст — никто не сможет управлять ботом")
        if not self.public_base_url.startswith("https://"):
            problems.append("PUBLIC_BASE_URL должен быть на https://")
        for name in ("db_password", "yookassa_shop_id", "yookassa_secret_key"):
            lowered = (
                getattr(self, name).lower().replace("_", "").replace("-", "")
            )
            if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
                problems.append(f"{name.upper()} содержит значение-заглушку")
        if problems:
            raise ValueError(
                "ENVIRONMENT=production, но конфигурация не готова:\n- "
                + "\n- ".join(problems)
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_database_url(self) -> str:
        """Строка подключения SQLAlchemy (asyncpg) для рантайма."""
        return self._build_dsn("postgresql+asyncpg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Строка подключения для инструментов без asyncio (psycopg2-free)."""
        return self._build_dsn("postgresql+asyncpg")

    def _build_dsn(self, driver: str) -> str:
        """Собирает DSN из реляционных компонентов.

        Args:
            driver: Драйвер SQLAlchemy, например ``postgresql+asyncpg``.

        Returns:
            Полная строка подключения.
        """
        from urllib.parse import quote_plus

        return (
            f"{driver}://{quote_plus(self.db_user)}:"
            f"{quote_plus(self.db_password)}@{self.db_host}:{self.db_port}"
            f"/{quote_plus(self.db_name)}"
        )

    @property
    def is_production(self) -> bool:
        """Признак боевого окружения."""
        return self.environment == "production"

    @property
    def is_admin(self) -> set[int]:
        """Множество Telegram ID администраторов для быстрых проверок."""
        return set(self.admin_ids)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Возвращает singleton настроек (кэшируется на процесс).

    Returns:
        Загруженный и валидированный экземпляр :class:`Settings`.
    """
    return Settings()  # type: ignore[call-arg]
