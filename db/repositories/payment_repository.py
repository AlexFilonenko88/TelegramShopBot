"""Репозиторий платежей."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from db.models.enums import PaymentProvider, PaymentStatus
from db.models.payment import Payment
from db.repositories.base_repository import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    """Запросы и мутации таблицы ``payments``."""

    model = Payment

    async def create(
        self,
        *,
        order_id: int,
        amount_kopecks: int,
        currency: str,
        provider: PaymentProvider = PaymentProvider.YOOKASSA,
    ) -> Payment:
        """Создаёт запись платежа до обращения к провайдеру.

        Запись появляется до HTTP-вызова, чтобы «потерянный» ответ
        YooKassa не оставил счёт без следа в нашей БД.
        """
        payment = Payment(
            order_id=order_id,
            amount_kopecks=amount_kopecks,
            currency=currency,
            provider=provider,
            status=PaymentStatus.PENDING,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def get_by_provider_id(
        self, provider: PaymentProvider, provider_payment_id: str
    ) -> Payment | None:
        """Ищет платёж по внешнему идентификатору (webhook)."""
        stmt = select(Payment).where(
            Payment.provider == provider,
            Payment.provider_payment_id == provider_payment_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_active_for_order(self, order_id: int) -> Payment | None:
        """Возвращает последний незавершённый платёж заказа.

        Нужен для повторного показа ссылки оплаты без создания нового
        счёта в YooKassa.
        """
        stmt = (
            select(Payment)
            .where(
                Payment.order_id == order_id,
                Payment.status.in_(
                    (PaymentStatus.PENDING, PaymentStatus.PROCESSING)
                ),
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def attach_provider_data(
        self,
        payment_id: int,
        *,
        provider_payment_id: str,
        confirmation_url: str | None,
        status: PaymentStatus,
        raw_response: dict,
    ) -> None:
        """Сохраняет ответ YooKassa о созданном счёте."""
        payment = await self.session.get(Payment, payment_id)
        if payment is None:
            return
        payment.provider_payment_id = provider_payment_id
        payment.confirmation_url = confirmation_url
        payment.status = status
        payment.raw_response = raw_response
        await self.session.flush()

    async def apply_provider_status(
        self,
        payment_id: int,
        *,
        status: PaymentStatus,
        raw_response: dict,
        paid_at: datetime | None = None,
    ) -> Payment | None:
        """Обновляет статус платежа по данным провайдера.

        Args:
            payment_id: ID записи в нашей БД.
            status: Новый статус.
            raw_response: Полный ответ провайдера (для аудита).
            paid_at: Время оплаты; подставляется текущее для успеха.

        Returns:
            Обновлённый платёж или ``None``, если записи нет.
        """
        payment = await self.session.get(Payment, payment_id)
        if payment is None:
            return None
        payment.status = status
        payment.raw_response = raw_response
        if status is PaymentStatus.SUCCEEDED and payment.paid_at is None:
            payment.paid_at = paid_at or datetime.now(UTC)
        await self.session.flush()
        return payment
