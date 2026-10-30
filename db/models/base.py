"""Базовый класс SQLAlchemy ORM и общие mixin-ы."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Декаративная база для всех моделей проекта."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: sa.DateTime(timezone=True),
        int: BigInteger(),
        bool: Boolean(),
        str: String(),
    }


def enum_column(
    enum_cls: type[StrEnum],
    *,
    name: str,
    nullable: bool = False,
) -> Any:
    """Колонка-перечисление, сохраняющая в БД *значения* членов enum.

    SQLAlchemy по умолчанию пишет в Postgres имена членов (``PENDING``),
    что делает данные нечитаемыми и ломает сверку с внешними API
    (YooKassa оперирует строчными статусами). Значения фиксируются явно.

    Args:
        enum_cls: Класс-перечисление (наследник :class:`StrEnum`).
        name: Имя типа ``ENUM`` в PostgreSQL (важно для миграций).
        nullable: Допускает ли колонка ``NULL``.

    Returns:
        Описание типа колонки для :func:`mapped_column`.
    """
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda obj: [member.value for member in obj],
        native_enum=True,
        nullable=nullable,
    )


class TimestampMixin:
    """Поля created_at / updated_at со значениями по умолчанию в БД."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )


class IdMixin:
    """Суррогатный целочисленный первичный ключ."""

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
