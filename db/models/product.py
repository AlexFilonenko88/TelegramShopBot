"""Модель цифрового товара."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from db.models.purchase import Purchase


class Product(Base, IdMixin, TimestampMixin):
    """Цифровой товар (курс, шаблон, чек-лист).

    Цена хранится в копейках целым числом: это исключает ошибки
    округления при расчётах и совпадает с форматом сумм YooKassa.

    Атрибуты:
        slug: Стабильный человекочитаемый идентификатор для кнопок
            и deep-link ссылок (``/buy/<slug>``).
        file_url: Внутренняя ссылка на файл товара; наружу выдаётся
            только владельцу покупки, никогда в каталоге.
    """

    __tablename__ = "products"

    slug: Mapped[str] = mapped_column(unique=True, nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False, default="")
    price_kopecks: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(nullable=False, default="RUB")
    file_url: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    purchases: Mapped[list[Purchase]] = relationship(back_populates="product")

    def __repr__(self) -> str:
        return f"<Product id={self.id} slug={self.slug!r}>"
