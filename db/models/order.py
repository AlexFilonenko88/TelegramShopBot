"""Модель заказа (одна или несколько позиций цифровых товаров)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base, IdMixin, TimestampMixin, enum_column
from db.models.enums import OrderStatus

if TYPE_CHECKING:
    from db.models.payment import Payment
    from db.models.purchase import Purchase
    from db.models.user import User


class Order(Base, IdMixin, TimestampMixin):
    """Заказ пользователя на один или несколько цифровых товаров.

    Атрибуты:
        total_kopecks: Итоговая сумма в копейках (целое число), как и
            цены товаров — исключает ошибки округления при расчётах.
        items_snapshot: Заморозка состава на момент оформления
            (slug, название, цена), чтобы правки каталога не влияли
            на уже созданные заказы.
    """

    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_user_status", "user_id", "status"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus, name="order_status"),
        default=OrderStatus.PENDING,
        index=True,
    )
    currency: Mapped[str] = mapped_column(default="RUB", nullable=False)
    total_kopecks: Mapped[int] = mapped_column(nullable=False)
    items_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    user: Mapped[User] = relationship(back_populates="orders")
    payments: Mapped[list[Payment]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    purchases: Mapped[list[Purchase]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_paid(self) -> bool:
        """Заказ оплачен и даёт доступ к товарам."""
        return self.status.is_paid

    @property
    def is_closed(self) -> bool:
        """Заказ в терминальном статусе и не подлежит изменению."""
        return self.status.is_terminal

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} user={self.user_id} "
            f"status={self.status.value}>"
        )
