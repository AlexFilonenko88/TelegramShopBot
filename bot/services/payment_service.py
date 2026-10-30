"""Бизнес-логика оформления заказа и оплаты.

Здесь принимаются все решения о деньгах: можно ли оплатить заказ,
какой статус считать успешным, создавать ли покупки и выдавать ли
товар. HTTP-детали YooKassa скрыты в :mod:`bot.services.yookassa_client`.

Порядок оплаты (flow):

1. :meth:`PaymentService.start_checkout` -- создаёт ``Order`` в статусе
   ``pending`` с заморозкой состава и цены (``items_snapshot``).
2. :meth:`PaymentService.create_payment` -- записывает ``Payment`` до
   обращения к провайдеру, затем создаёт счёт в YooKassa и сохраняет
   ``confirmation_url``; заказ переходит в ``awaiting_payment``.
3. При успешной оплате статус применяется либо webhook-ом
   (:meth:`handle_provider_event`), либо кнопкой «Проверить оплату»
   (:meth:`sync_payment_status`) -- обе дороги идут в общий
   :meth:`_settle_order`.
4. :meth:`_settle_order` атомарно переводит заказ в ``paid`` и создаёт
   покупки; выдачу файлов выполняет handler и подтверждает через
   :meth:`mark_delivered`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from db.models.enums import OrderStatus, PaymentProvider, PaymentStatus
from db.models.order import Order
from db.repositories.order_repository import OrderRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.purchase_repository import PurchaseRepository

from bot.services.errors import (
    OrderNotFoundError,
    OrderStateError,
    PaymentFailedError,
    PaymentNotFoundError,
)
from bot.services.money import format_price
from bot.services.product_service import ProductCard
from bot.services.yookassa_client import YooKassaClient, map_provider_status

logger = logging.getLogger(__name__)

CHECKOUT_DESCRIPTION_LIMIT = 128
"""Максимум символов в ``description`` счёта YooKassa."""


@dataclass(frozen=True)
class Checkout:
    """Итог оформления заказа: что покупать и сколько платить.

    Attributes:
        order_id: ID созданного заказа.
        product: Карточка товара.
        total_kopecks: Сумма к оплате.
        total_label: Отформатированная сумма для текста сообщения.
    """

    order_id: int
    product: ProductCard
    total_kopecks: int
    total_label: str


@dataclass(frozen=True)
class PaymentLink:
    """Счёт, созданный в платёжной системе.

    Attributes:
        order_id: Наш заказ.
        payment_id: Наша запись платежа.
        provider_payment_id: Идентификатор счёта в YooKassa.
        confirmation_url: Ссылка для пользователя.
        total_label: Сумма счёта в человекочитаемом виде — текст «счёт
            создан на ...» берётся отсюда, чтобы хендлер не пересчитывал
            копейки сам.
    """

    order_id: int
    payment_id: int
    provider_payment_id: str
    confirmation_url: str
    total_label: str


@dataclass(frozen=True)
class DeliveryItem:
    """Позиция заказа, готовая к выдаче покупателю.

    Attributes:
        purchase_id: ID покупки — его подтверждает :meth:`mark_delivered`.
        product_id: ID товара.
        title: Название для подписи файла и текста.
        file_url: Ссылка на материалы (только для владельца покупки).
    """

    purchase_id: int
    product_id: int
    title: str
    file_url: str


class PaymentService:
    """Оформление, оплата и подтверждение заказов."""

    def __init__(
        self,
        orders: OrderRepository,
        payments: PaymentRepository,
        purchases: PurchaseRepository,
        client: YooKassaClient,
        *,
        return_url: str,
    ) -> None:
        """Args:
        orders: Репозиторий заказов.
        payments: Репозиторий платежей.
        purchases: Репозиторий покупок.
        client: Клиент YooKassa.
        return_url: Куда провайдер вернёт пользователя после оплаты.
        """
        self._orders = orders
        self._payments = payments
        self._purchases = purchases
        self._client = client
        self._return_url = return_url

    async def start_checkout(
        self, *, user_id: int, product: ProductCard
    ) -> Checkout:
        """Создаёт заказ на один товар.

        Цена фиксируется в момент оформления, поэтому изменение цен в
        каталоге не влияет на уже начатую покупку.

        Args:
            user_id: Telegram ID покупателя.
            product: Карточка товара (получена через ProductService).

        Returns:
            Данные заказа для сообщения подтверждения.
        """
        snapshot = {
            "items": [
                {
                    "product_id": product.id,
                    "slug": product.slug,
                    "title": product.title,
                    "price_kopecks": product.price_kopecks,
                }
            ]
        }
        order = await self._orders.create(
            user_id=user_id,
            total_kopecks=product.price_kopecks,
            currency=product.currency,
            items_snapshot=snapshot,
        )
        logger.info(
            "Заказ %s создан: user=%s product=%s %s",
            order.id,
            user_id,
            product.slug,
            order.total_kopecks,
        )
        return Checkout(
            order_id=order.id,
            product=product,
            total_kopecks=order.total_kopecks,
            total_label=format_price(order.total_kopecks, order.currency),
        )

    async def create_payment(
        self, *, user_id: int, order_id: int
    ) -> PaymentLink:
        """Создаёт счёт в YooKassa для заказа.

        Если у заказа уже есть незавершённый счёт, он возвращается без
        нового HTTP-запроса: повторное нажатие «Оплатить» не плодит
        дубли в платёжной системе.

        Args:
            user_id: Telegram ID покупателя (защита чужих заказов).
            order_id: ID заказа.

        Returns:
            Ссылку на оплату.

        Raises:
            OrderNotFoundError: Заказ не найден.
            OrderStateError: Заказ принадлежит другому пользователю или
                уже оплачен/закрыт.
        """
        order = await self._require_open_order(user_id, order_id)
        existing = await self._payments.get_active_for_order(order.id)
        if existing is not None and existing.provider_payment_id:
            logger.info(
                "Заказ %s: возвращаем существующий счёт %s",
                order.id,
                existing.provider_payment_id,
            )
            return PaymentLink(
                order_id=order.id,
                payment_id=existing.id,
                provider_payment_id=existing.provider_payment_id,
                confirmation_url=existing.confirmation_url or self._return_url,
                total_label=format_price(order.total_kopecks, order.currency),
            )

        payment = await self._payments.create(
            order_id=order.id,
            amount_kopecks=order.total_kopecks,
            currency=order.currency,
        )
        intent = await self._client.create_payment(
            idempotency_key=str(payment.id),
            amount_kopecks=order.total_kopecks,
            currency=order.currency,
            description=self._describe(order),
            return_url=self._return_url,
            metadata={"order_id": str(order.id), "user_id": str(user_id)},
        )
        await self._payments.attach_provider_data(
            payment.id,
            provider_payment_id=intent.provider_payment_id,
            confirmation_url=intent.confirmation_url,
            status=intent.status,
            raw_response=intent.raw_response,
        )
        await self._orders.transition(
            order.id,
            from_statuses=(OrderStatus.PENDING, OrderStatus.AWAITING_PAYMENT),
            to=OrderStatus.AWAITING_PAYMENT,
        )
        if intent.confirmation_url is None:
            raise PaymentFailedError("провайдер не вернул ссылку оплаты")
        logger.info(
            "Заказ %s: счёт %s создан, статус %s",
            order.id,
            intent.provider_payment_id,
            intent.status.value,
        )
        return PaymentLink(
            order_id=order.id,
            payment_id=payment.id,
            provider_payment_id=intent.provider_payment_id,
            confirmation_url=intent.confirmation_url,
            total_label=format_price(order.total_kopecks, order.currency),
        )

    async def sync_payment_status(self, *, user_id: int, order_id: int) -> bool:
        """Актуализирует статус заказа запросом к провайдеру.

        Вызывается кнопкой «Проверить оплату» и после возврата с
        платёжной страницы: webhook может запаздывать, поэтому статус
        переспрашиваем напрямую.

        Args:
            user_id: Telegram ID покупателя.
            order_id: ID заказа.

        Returns:
            ``True``, если заказ оплачен и требует выдачи товаров.
        """
        order = await self._orders.get_with_relations(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)
        if order.user_id != user_id:
            logger.warning(
                "Попытка проверить чужой заказ: order=%s user=%s owner=%s",
                order_id,
                user_id,
                order.user_id,
            )
            raise OrderNotFoundError(order_id)
        payment = await self._payments.get_active_for_order(order_id)
        if payment is None or not payment.provider_payment_id:
            return False
        intent = await self._client.get_payment(payment.provider_payment_id)
        await self._payments.apply_provider_status(
            payment.id,
            status=intent.status,
            raw_response=intent.raw_response,
        )
        return await self._settle_order(order_id, intent.status)

    async def handle_provider_event(
        self,
        *,
        provider_payment_id: str,
        raw_status: str,
        raw_response: dict[str, Any],
    ) -> list[int]:
        """Обрабатывает webhook-уведомление о платеже.

        Args:
            provider_payment_id: Идентификатор счёта в YooKassa.
            raw_status: Статус из уведомления (``succeeded`` и т. п.).
            raw_response: Полный JSON уведомления для аудита.

        Returns:
            ID товаров, которые нужно выдать, либо пустой список, если
            выдача уже выполнена (идемпотентный повтор уведомления).

        Raises:
            PaymentNotFoundError: Уведомление о неизвестном счёте.
            UnknownPaymentStatusError: Провайдер прислал статус, которого
                нет в модели (обычно это тестовая отправка из ЛК).
        """
        payment = await self._payments.get_by_provider_id(
            provider=PaymentProvider.YOOKASSA,
            provider_payment_id=provider_payment_id,
        )
        if payment is None:
            raise PaymentNotFoundError(provider_payment_id)
        status = map_provider_status(raw_status)
        await self._payments.apply_provider_status(
            payment.id, status=status, raw_response=raw_response
        )
        settled = await self._settle_order(payment.order_id, status)
        if not settled:
            return []
        order = await self._orders.get_with_relations(payment.order_id)
        if order is None:
            return []
        return _product_ids_of(order)

    async def cancel_order(self, *, user_id: int, order_id: int) -> bool:
        """Отменяет неоплаченный заказ по желанию покупателя.

        Отмена локальная: счёта в YooKassa бот не отменяет (клиент
        умеет только создавать и читать), он просто протухает по
        таймауту провайдера. Если платёж всё же пройдёт позже, заказ уже
        в терминальном статусе и :meth:`_settle_order` не создаст
        покупок — такие случаи разбирает администратор вручную
        (возврат), поэтому статус ``refunded`` в схеме предусмотрен.

        Args:
            user_id: Telegram ID покупателя.
            order_id: ID заказа.

        Returns:
            ``True``, если заказ удалось перевести в ``canceled``.

        Raises:
            OrderNotFoundError: Заказ не найден или чужой.
        """
        order = await self._require_open_order(user_id, order_id)
        moved = await self._orders.transition(
            order.id,
            from_statuses=(OrderStatus.PENDING, OrderStatus.AWAITING_PAYMENT),
            to=OrderStatus.CANCELED,
        )
        if moved:
            logger.info("Заказ %s отменён пользователем %s", order.id, user_id)
        return moved

    async def delivery_items(
        self, *, user_id: int, order_id: int
    ) -> list[DeliveryItem]:
        """Материалы заказа, которые ещё не выданы этому покупателю.

        Args:
            user_id: Telegram ID покупателя (защита чужих ссылок).
            order_id: ID заказа.

        Returns:
            Список позиций для отправки файлов.

        Raises:
            OrderNotFoundError: Заказ не найден или принадлежит другим.
        """
        order = await self._orders.get_with_relations(order_id)
        if order is None or order.user_id != user_id:
            raise OrderNotFoundError(order_id)
        undelivered = {
            purchase.id
            for purchase in await self._purchases.list_undelivered(order_id)
        }
        items: list[DeliveryItem] = []
        for purchase, product in await self._purchases.list_with_products(
            order_id=order_id
        ):
            if purchase.id in undelivered:
                items.append(
                    DeliveryItem(
                        purchase_id=purchase.id,
                        product_id=product.id,
                        title=product.title,
                        file_url=product.file_url,
                    )
                )
        return items

    async def mark_delivered(self, purchase_ids: list[int]) -> None:
        """Подтверждает, что материалы отправлены покупателю.

        Args:
            purchase_ids: ID покупок, по которым прошла отправка.
        """
        for purchase_id in purchase_ids:
            await self._purchases.mark_delivered(purchase_id)

    async def pending_purchases(self, order_id: int) -> list[int]:
        """ID покупок заказа, которые ещё не выданы.

        Нужен для повторной выдачи после сбоя Telegram API.
        """
        purchases = await self._purchases.list_undelivered(order_id)
        return [purchase.id for purchase in purchases]

    async def count_stats(self) -> tuple[int, int]:
        """Число оплаченных заказов и выручка в копейках (для ``/stats``).

        Returns:
            Пару ``(paid_orders, revenue_kopecks)``.
        """
        return (
            await self._orders.count_paid(),
            await self._orders.sum_paid_kopecks(),
        )

    async def _settle_order(self, order_id: int, status: PaymentStatus) -> bool:
        """Применяет статус платежа к заказу и создаёт покупки.

        Успех засчитывается только тому вызову, который сумел перевести
        заказ из «открытого» состояния в ``paid``: повторная доставка
        webhook или двойное нажатие кнопки не создадут дубли покупок.

        Args:
            order_id: ID заказа.
            status: Новый статус платежа.

        Returns:
            ``True``, если заказ только что стал оплачен (нужна выдача).
        """
        if status is PaymentStatus.SUCCEEDED:
            moved = await self._orders.transition(
                order_id,
                from_statuses=(
                    OrderStatus.PENDING,
                    OrderStatus.AWAITING_PAYMENT,
                ),
                to=OrderStatus.PAID,
            )
            if not moved:
                logger.debug(
                    "Заказ %s уже оплачен — повтор игнорируется", order_id
                )
                return False
            order = await self._orders.get_with_relations(order_id)
            if order is None:
                return False
            for product_id in _product_ids_of(order):
                await self._purchases.create(
                    user_id=order.user_id,
                    order_id=order.id,
                    product_id=product_id,
                )
            logger.info(
                "Заказ %s оплачен, товаров: %d",
                order_id,
                len(order.items_snapshot.get("items", [])),
            )
            return True
        if status is PaymentStatus.CANCELED:
            await self._orders.transition(
                order_id,
                from_statuses=(
                    OrderStatus.PENDING,
                    OrderStatus.AWAITING_PAYMENT,
                ),
                to=OrderStatus.CANCELED,
            )
        return False

    async def _require_open_order(self, user_id: int, order_id: int) -> Order:
        """Возвращает заказ, разрешённый к оплате этим пользователем.

        Raises:
            OrderNotFoundError: Заказ не существует.
            OrderStateError: Заказ чужой или уже закрыт.
        """
        order = await self._orders.get_with_relations(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)
        if order.user_id != user_id:
            logger.warning(
                "Попытка оплатить чужой заказ: order=%s user=%s owner=%s",
                order_id,
                user_id,
                order.user_id,
            )
            raise OrderNotFoundError(order_id)
        if order.is_closed:
            raise OrderStateError(
                order_id, order.status.value, "awaiting_payment"
            )
        return order

    @staticmethod
    def _describe(order: Order) -> str:
        """Короткое описание счёта для платёжной формы и чека."""
        items = order.items_snapshot.get("items", [])
        titles = ", ".join(item.get("title", "") for item in items)
        return f"Заказ N{order.id}: {titles}"[:CHECKOUT_DESCRIPTION_LIMIT]


def _product_ids_of(order: Order) -> list[int]:
    """Список ID товаров из замороженного состава заказа."""
    items = order.items_snapshot.get("items", [])
    return [int(item["product_id"]) for item in items if "product_id" in item]
