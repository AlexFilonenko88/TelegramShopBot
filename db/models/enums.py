"""Перечисления статусов, используемые моделями и сервисами."""

from __future__ import annotations

from enum import StrEnum

import sqlalchemy as sa


def pg_enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """Возвращает колонку-enum на значениях, а не на именах членов.

    Без ``values_callable`` SQLAlchemy пишет в БД имена (``PENDING``),
    тогда как весь код и внешние API оперируют значениями (``pending``).

    Args:
        enum_cls: Класс перечисления на базе :class:`StrEnum`.
        name: Имя типа данных в PostgreSQL.

    Returns:
        Готовый к использованию тип колонки.
    """
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda obj: [member.value for member in obj],
    )


class OrderStatus(StrEnum):
    """Статусы заказа."""

    PENDING = "pending"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    CANCELED = "canceled"
    FAILED = "failed"
    REFUNDED = "refunded"

    @property
    def is_terminal(self) -> bool:
        """Заказ больше не может измениться автоматически."""
        return self in {
            OrderStatus.PAID,
            OrderStatus.CANCELED,
            OrderStatus.FAILED,
            OrderStatus.REFUNDED,
        }

    @property
    def is_paid(self) -> bool:
        """Заказ оплачен и даёт доступ к товару."""
        return self is OrderStatus.PAID


class PaymentStatus(StrEnum):
    """Статусы платежа во внешнем провайдере."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"

    @property
    def is_paid(self) -> bool:
        """Платёж успешно завершён."""
        return self is PaymentStatus.SUCCEEDED


class PaymentProvider(StrEnum):
    """Платёжные провайдеры, поддерживаемые ботом."""

    YOOKASSA = "yookassa"
