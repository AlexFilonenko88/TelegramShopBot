"""Общая база репозиториев.

Репозиторий — единственное место, где уместны SQL-запросы. Сессия
передаётся извне (middleware), чтобы один запрос бота жил в одной
транзакции со всеми репозиториями.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.base import Base


class BaseRepository[ModelT: Base]:
    """Хранит модель и сессию, предоставляет общие операции.

    Attributes:
        model: Класс модели, с которой работает репозиторий.
        session: Активная сессия БД.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        """Args: session: Сессия БД (обычно из middleware)."""
        self.session = session

    async def get_by_id(self, entity_id: int) -> ModelT | None:
        """Возвращает запись по первичному ключу или ``None``."""
        return await self.session.get(self.model, entity_id)

    async def add(self, entity: ModelT) -> ModelT:
        """Добавляет сущность в сессию (flush — на усмотрение вызывающего)."""
        self.session.add(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Удаляет сущность."""
        await self.session.delete(entity)

    async def flush(self) -> None:
        """Отправляет накопленные изменения в БД, не завершая транзакцию."""
        await self.session.flush()
