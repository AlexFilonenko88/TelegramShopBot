"""Модель платежа во внешнем платёжном провайдере."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base, IdMixin, TimestampMixin, enum_column
from db.models.enums import PaymentProvider, PaymentStatus

if TYPE_CHECKING:
    from db.models.order import Order


class Payment(Base, IdMixin, TimestampMixin):
    """Счёт, созданный в платёжной системе для заказа.

    Хранит внешний идентификатор, чтобы сверять статус по webhook и
    при повторных попытках. Один заказ может иметь несколько платежей
    (например, после отмены и новой попытки оплаты).

    Атрибуты:
        amount_kopecks: Сумма в копейках — в том же формате, что цены.
        provider_payment_id: Идентификатор платежа на стороне провайдера.
        raw_response: Последний ответ провайдера для аудита разборов.
    """

    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_order_status", "order_id", "status"),)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        enum_column(PaymentProvider, name="payment_provider"),
        default=PaymentProvider.YOOKASSA,
    )
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    amount_kopecks: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="RUB"
    )
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus, name="payment_status"),
        default=PaymentStatus.PENDING,
        index=True,
    )
    confirmation_url: Mapped[str | None] = mapped_column(nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(nullable=True)
    raw_response: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    order: Mapped[Order] = relationship(back_populates="payments")

    @property
    def is_succeeded(self) -> bool:
        """Платёж успешно проведён на стороне провайдера."""
        return self.status.is_paid

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} order={self.order_id} "
            f"status={self.status.value}>"
        )
