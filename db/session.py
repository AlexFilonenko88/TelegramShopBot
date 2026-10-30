"""Асинхронные сессии SQLAlchemy и движок.

Движок и фабрика сессий создаются один раз при старте приложения.
Ручные вызовы ``create_engine`` в остальном коде не используются —
сессия приходит через middleware (``db_retriever``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str, *, echo: bool = False, **kwargs: Any) -> AsyncEngine:
    """Создаёт и кэширует движок приложения.

    Args:
        url: Строка подключения (``postgresql+asyncpg://...``).
        echo: Логировать ли SQL-запросы (только для разработки).
        **kwargs: Дополнительные аргументы :func:`create_async_engine`
            (пул соединений, таймауты).

    Returns:
        Созданный движок.
    """
    global _engine, _session_factory
    engine_kwargs: dict[str, Any] = {
        "echo": echo,
        "pool_pre_ping": True,
        "pool_size": kwargs.pop("pool_size", 5),
        "max_overflow": kwargs.pop("max_overflow", 10),
        **kwargs,
    }
    _engine = create_async_engine(url, **engine_kwargs)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return _engine


def get_engine() -> AsyncEngine:
    """Возвращает движок приложения.

    Returns:
        Инициализированный движок.

    Raises:
        RuntimeError: Если :func:`init_engine` ещё не вызывался.
    """
    if _engine is None:
        raise RuntimeError(
            "Движок БД не инициализирован: вызовите init_engine()"
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Возвращает фабрику сессий приложения.

    Raises:
        RuntimeError: Если :func:`init_engine` ещё не вызывался.
    """
    if _session_factory is None:
        raise RuntimeError("Фабрика сессий не инициализирована: init_engine()")
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Отдаёт сессию с коммитом на успех и откатом на ошибку.

    Используется как асинхронный контекстный менеджер и как зависимость
    aiogram (``Depends(session_scope)`` через middleware).

    Yields:
        Активная :class:`AsyncSession`.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Закрывает пул соединений (вызывается при остановке приложения)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
