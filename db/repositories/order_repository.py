"""Репозиторий заказов."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from db.models.enums import OrderStatus
from db.models.order import Order
from db.repositories.base_repository import BaseRepository

OPEN_STATUSES = (OrderStatus.PENDING, OrderStatus.AWAITING_PAYMENT)
"""Статусы заказа, который ещё можно оплатить."""


class OrderRepository(BaseRepository[Order]):
    """Запросы и мутации таблицы ``orders``."""

    model = Order

    async def create(
        self,
        *,
        user_id: int,
        total_kopecks: int,
        currency: str,
        items_snapshot: dict,
    ) -> Order:
        """Создаёт заказ в статусе ``pending``.

        Args:
            user_id: Telegram ID покупателя.
            total_kopecks: Итоговая сумма в копейках.
            currency: Код валюты заказа.
            items_snapshot: Заморозка состава заказа.

        Returns:
            Созданный заказ с заполненным ``id``.
        """
        order = Order(
            user_id=user_id,
            total_kopecks=total_kopecks,
            currency=currency,
            items_snapshot=items_snapshot,
            status=OrderStatus.PENDING,
        )
        self.session.add(order)
        await self.session.flush()
        return order

    async def get_with_relations(self, order_id: int) -> Order | None:
        """Возвращает заказ вместе с платежами и покупками.

        Используется обработчиком оплаты, где нужны связанные записи
        без дополнительных запросов.
        """
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.payments), selectinload(Order.purchases)
            )
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_open_for_user(self, user_id: int) -> list[Order]:
        """Возвращает неоплаченные заказы пользователя (для «продолжить»)."""
        stmt = (
            select(Order)
            .where(Order.user_id == user_id, Order.status.in_(OPEN_STATUSES))
            .order_by(Order.created_at.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def transition(
        self,
        order_id: int,
        *,
        from_statuses: tuple[OrderStatus, ...],
        to: OrderStatus,
    ) -> bool:
        """Атомарно переводит заказ в новый статус.

        Условие ``status IN from_statuses`` в самом UPDATE защищает от
        гонки: если webhook и кнопка «проверить оплату» сработают
        одновременно, успех обработает только один вызов.

        Args:
            order_id: ID заказа.
            from_statuses: Разрешённые исходные статусы.
            to: Целевой статус.

        Returns:
            ``True``, если заказ найден и переведён, иначе ``False``.
        """
        stmt = (
            update(Order)
            .where(Order.id == order_id, Order.status.in_(from_statuses))
            .values(status=to)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (result.rowcount or 0) > 0

    async def list_recent(self, limit: int = 20) -> list[Order]:
        """Последние заказы (сводка для админ-команды ``/stats``)."""
        stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def count_paid(self) -> int:
        """Число оплаченных заказов."""
        stmt = select(Order.id).where(Order.status == OrderStatus.PAID)
        return len((await self.session.scalars(stmt)).all())

    async def sum_paid_kopecks(self) -> int:
        """Сумма всех оплаченных заказов в копейках."""
        stmt = select(Order.total_kopecks).where(
            Order.status == OrderStatus.PAID
        )
        return sum((await self.session.scalars(stmt)).all())
