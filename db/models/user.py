"""Модель пользователя Telegram."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.models.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from db.models.order import Order
    from db.models.purchase import Purchase


class User(Base, IdMixin, TimestampMixin):
    """Аккаунт Telegram с профилем и историей покупок.

    Атрибуты:
        id: Telegram ID пользователя (первичный ключ).
        username: ``@username`` (без ``@``).
        first_name: Имя пользователя.
        last_name: Фамилия пользователя.
        language_code: Язык интерфейса Telegram клиента.
        preferred_language: Язык, выбранный самим пользователем в боте;
            ``None`` — значит «как в Telegram».
        is_admin: Является ли пользователь администратором бота.
        is_active: Активен ли пользователь (false — заблокирован).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    last_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    language_code: Mapped[str] = mapped_column(
        String(8), nullable=False, default="ru"
    )
    preferred_language: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    orders: Mapped[list[Order]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    purchases: Mapped[list[Purchase]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"
