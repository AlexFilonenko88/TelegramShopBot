"""Репозиторий покупок (выданных доступов к товарам)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from db.models.product import Product
from db.models.purchase import Purchase
from db.repositories.base_repository import BaseRepository


class PurchaseRepository(BaseRepository[Purchase]):
    """Запросы и мутации таблицы ``purchases``.

    Покупка — факт права пользователя на товар. Она создаётся в момент
    подтверждения оплаты, а ``delivered_at`` проставляется после того,
    как бот реально отправил материалы. Разделение нужно для надёжной
    выдачи: если отправка упала, покупка уже существует и её можно
    довыдать повторной кнопкой, не создавая дубль.
    """

    model = Purchase

    async def create(
        self, *, user_id: int, order_id: int, product_id: int
    ) -> Purchase:
        """Создаёт покупку в состоянии «оплачено, не выдано».

        Args:
            user_id: Telegram ID покупателя.
            order_id: ID оплаченного заказа.
            product_id: ID товара из состава заказа.

        Returns:
            Созданная запись покупки.
        """
        purchase = Purchase(
            user_id=user_id,
            order_id=order_id,
            product_id=product_id,
        )
        self.session.add(purchase)
        await self.session.flush()
        return purchase

    async def list_for_user(self, user_id: int) -> list[Purchase]:
        """История покупок пользователя, новые сверху.

        Без связанных товаров: для показа списка с названиями есть
        :meth:`list_with_products`, который делает один join-запрос
        вместо N обращений к ``purchase.product`` в цикле.
        """
        stmt = (
            select(Purchase)
            .where(Purchase.user_id == user_id)
            .order_by(Purchase.created_at.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_undelivered(self, order_id: int) -> list[Purchase]:
        """Покупки заказа, которые ещё не выданы покупателю."""
        stmt = select(Purchase).where(
            Purchase.order_id == order_id,
            Purchase.delivered_at.is_(None),
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_with_products(
        self, *, user_id: int | None = None, order_id: int | None = None
    ) -> list[tuple[Purchase, Product]]:
        """Покупки вместе с товарами: названия и цены для показа.

        Держать join здесь, а не в сервисе, требует то же правило, что и
        для остального SQL: запрос знает только репозиторий.

        Args:
            user_id: Фильтр по покупателю.
            order_id: Фильтр по заказу.

        Returns:
            Пары ``(покупка, товар)`` от новых к старым.

        Raises:
            ValueError: Если не задан ни один фильтр — такие запросы
                вернули бы всю таблицу.
        """
        if user_id is None and order_id is None:
            raise ValueError("Нужен фильтр по user_id или order_id")
        stmt = (
            select(Purchase, Product)
            .join(Product, Purchase.product_id == Product.id)
            .order_by(Purchase.created_at.desc())
        )
        if user_id is not None:
            stmt = stmt.where(Purchase.user_id == user_id)
        if order_id is not None:
            stmt = stmt.where(Purchase.order_id == order_id)
        return [
            (row[0], row[1]) for row in (await self.session.execute(stmt)).all()
        ]

    async def has_purchase(self, user_id: int, product_id: int) -> bool:
        """Покупал ли пользователь товар (проверка права на выдачу)."""
        stmt = (
            select(Purchase.id)
            .where(
                Purchase.user_id == user_id,
                Purchase.product_id == product_id,
            )
            .limit(1)
        )
        return (
            await self.session.execute(stmt)
        ).scalar_one_or_none() is not None

    async def mark_delivered(self, purchase_id: int) -> Purchase | None:
        """Фиксирует факт отправки материалов покупателю.

        Повторный вызов ничего не меняет: ``delivered_at`` остаётся равным
        времени первой выдачи, иначе аудит «когда покупатель получил файл»
        терялся бы при каждом повторе выдачи.
        """
        purchase = await self.session.get(Purchase, purchase_id)
        if purchase is None or purchase.delivered_at is not None:
            return purchase
        purchase.delivered_at = datetime.now(UTC)
        await self.session.flush()
        return purchase
