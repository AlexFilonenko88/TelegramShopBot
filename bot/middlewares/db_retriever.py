"""Middleware, дающий обработчикам сессию БД и готовые сервисы.

Соглашение проекта: хендлеры не открывают сессии сами и не пишут
запросов. Один апдейт = одна транзакция: :class:`DbSessionMiddleware`
создаёт сессию, кладёт её и сконструированные репозитории/сервисы в
контекст, а по итогу коммитит (или откатывает при исключении).

Сессия намеренно открывается лениво — только для событий, у которых есть
пользователь. ``typing`` и прочие «служебные» апдейты не должны
вытаскивать соединение из пула.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from db.repositories.order_repository import OrderRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.product_repository import ProductRepository
from db.repositories.purchase_repository import PurchaseRepository
from db.repositories.user_repository import UserRepository
from db.session import get_session_factory
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.payment_service import PaymentService
from bot.services.product_service import ProductService
from bot.services.user_service import UserService
from bot.services.yookassa_client import YooKassaClient

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Оборачивает обработку апдейта в транзакцию БД."""

    def __init__(
        self, yookassa_client: YooKassaClient, *, return_url: str
    ) -> None:
        """Args:
        yookassa_client: Общий клиент YooKassa (создаётся в ``main``).
        return_url: Куда провайдер вернёт покупателя после оплаты.
        """
        self._client = yookassa_client
        self._return_url = return_url

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Открывает сессию, вызывает обработчик, коммитит изменения.

        Args:
            handler: Следующий в цепочке обработчик.
            event: Входящий апдейт.
            data: Контекст, доступный хендлеру по именам параметров.

        Returns:
            Результат работы обработчика.
        """
        if getattr(event, "from_user", None) is None:
            return await handler(event, data)

        async with get_session_factory()() as session:
            self._inject(session, data)
            try:
                result = await handler(event, data)
            except Exception:
                await session.rollback()
                logger.exception("Откат транзакции из-за ошибки обработчика")
                raise
            await session.commit()
            return result

    def _inject(self, session: AsyncSession, data: dict[str, Any]) -> None:
        """Кладёт сессию, репозитории и сервисы в контекст обработчика."""
        users = UserRepository(session)
        products = ProductRepository(session)
        orders = OrderRepository(session)
        payments = PaymentRepository(session)
        purchases = PurchaseRepository(session)

        data["session"] = session
        data["users"] = users
        data["products"] = products
        data["orders"] = orders
        data["payments"] = payments
        data["purchases"] = purchases
        data["user_service"] = UserService(users)
        data["product_service"] = ProductService(products, purchases)
        data["payment_service"] = PaymentService(
            orders,
            payments,
            purchases,
            self._client,
            return_url=self._return_url,
        )
