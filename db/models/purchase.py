"""Модель покупки: факт выданного доступа к товару."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from db.models.order import Order
    from db.models.product import Product
    from db.models.user import User


class Purchase(Base, IdMixin, TimestampMixin):
    """Выдача товара пользователю после успешной оплаты.

    Заказ может содержать несколько товаров, поэтому покупки хранятся
    отдельно. Пара ``(order_id, product_id)`` уникальна: повторная
    выдача того же товара в рамках заказа невозможна.

    Атрибуты:
        delivered_at: Когда покупателю отправлены материалы.
            ``None`` означает «оплачено, но ещё не выдано».
    """

    __tablename__ = "purchases"
    __table_args__ = (
        UniqueConstraint(
            "order_id", "product_id", name="uq_purchase_order_product"
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="purchases")
    order: Mapped[Order] = relationship(back_populates="purchases")
    product: Mapped[Product] = relationship(back_populates="purchases")

    def __repr__(self) -> str:
        return (
            f"<Purchase id={self.id} user={self.user_id} "
            f"product={self.product_id}>"
        )
