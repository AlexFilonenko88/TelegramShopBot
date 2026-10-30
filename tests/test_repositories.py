"""Интеграционные тесты репозиториев и сервисов на реальной БД.

Без PostgreSQL тесты пропускаются: прогон не должен требовать поднятого
сервера, но и не должен делать вид, что SQL проверен.

Подключение берётся из ``.env`` (``DB_*``). Для локального прогона
достаточно временного кластера — см. README.
"""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from bot.services.errors import (
    AlreadyPurchasedError,
    NotPurchasedError,
    ProductUnavailableError,
)
from bot.services.payment_service import PaymentService
from bot.services.product_service import ProductService
from bot.services.user_service import UserService
from bot.services.yookassa_client import PaymentIntent
from db.models.enums import OrderStatus, PaymentProvider, PaymentStatus
from db.models.product import Product
from db.repositories.order_repository import OrderRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.product_repository import ProductRepository
from db.repositories.purchase_repository import PurchaseRepository
from db.repositories.user_repository import UserRepository
from db.session import dispose_engine, get_session_factory, init_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _database_available() -> bool:
    """Проверяет соединение до начала тестов."""
    from config import get_settings

    try:
        init_engine(get_settings().async_database_url)
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        await dispose_engine()
        return False


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Сессия с откатом после теста: база остаётся чистой.

    Готовность БД проверяется здесь, а не в module-scope фикстуре:
    pytest-asyncio не даёт смешивать области видимости, а без сервера
    тесты должны именно пропускаться.
    """
    if not await _database_available():
        pytest.skip("PostgreSQL недоступен: интеграционные тесты пропущены")
    async with get_session_factory()() as db_session:
        yield db_session
        await db_session.rollback()
    await dispose_engine()


@pytest.fixture
async def unique_suffix() -> AsyncIterator[str]:
    """Уникальный суффикс, чтобы тесты не мешали друг другу."""
    import uuid

    yield uuid.uuid4().hex[:8]


@pytest.fixture
async def buyer(session: AsyncSession, unique_suffix: str):
    """Реальный пользователь: на него ссылаются заказы и покупки (FK)."""
    tg_id = 900000000 + int(unique_suffix[:6], 16) % 90000000
    return await UserRepository(session).upsert(
        tg_id=tg_id,
        username=f"buyer_{unique_suffix}",
        first_name="Покупатель",
        last_name="",
        language_code="ru",
        is_admin=False,
    )


async def make_product(session: AsyncSession, suffix: str) -> Product:
    """Создаёт активный товар с уникальным slug."""
    return await ProductRepository(session).create_product(
        title=f"Товар {suffix}",
        description="Описание",
        price_kopecks=150000,
        file_url=f"https://files.example/{suffix}.pdf",
        slug=f"tovar-{suffix}",
    )


def snapshot_of(product: Product) -> dict[str, Any]:
    """Заморозка состава заказа в том же виде, что и ``start_checkout``.

    ``_product_ids_of`` читает ``items[*].product_id`` — тесты обязаны
    писать идентичную структуру, иначе проверяли бы не тот код.
    """
    return {
        "items": [
            {
                "product_id": product.id,
                "slug": product.slug,
                "title": product.title,
                "price_kopecks": product.price_kopecks,
            }
        ]
    }


async def make_order(
    session: AsyncSession, user_id: int, product: Product
) -> int:
    """Заказ на один товар: у покупки обязателен существующий ``order_id``."""
    order = await OrderRepository(session).create(
        user_id=user_id,
        total_kopecks=product.price_kopecks,
        currency=product.currency,
        items_snapshot=snapshot_of(product),
    )
    return order.id


def client_returning(*intents: PaymentIntent) -> MagicMock:
    """Клиент YooKassa, отдающий заготовленные ответы по одному вызову."""
    client = MagicMock()
    client.get_payment = AsyncMock(side_effect=list(intents))
    return client


async def test_user_upsert_is_idempotent(session: AsyncSession) -> None:
    """Повторный вход обновляет профиль, но не создаёт дубль."""
    service = UserService(UserRepository(session))
    tg_id = 900000001

    first = await service.register(
        tg_id=tg_id,
        username="old",
        first_name="Имя",
        last_name="",
        language_code="ru",
        is_admin=False,
    )
    second = await service.register(
        tg_id=tg_id,
        username="new",
        first_name="Имя",
        last_name="",
        language_code="ru",
        is_admin=True,
    )
    assert first.id == second.id
    assert second.username == "new"
    assert second.is_admin is True
    assert await UserRepository(session).count_active() >= 1


async def test_set_language_persists(session: AsyncSession) -> None:
    """Выбранный язык сохраняется и попадает в профиль."""
    service = UserService(UserRepository(session))
    tg_id = 900000002
    user = await service.register(
        tg_id=tg_id,
        username=None,
        first_name="Язык",
        last_name="",
        language_code="en-US",
        is_admin=False,
    )
    await service.set_language(tg_id, "en")
    await session.refresh(user)
    assert user.preferred_language == "en"


async def test_profile_language_prefers_saved(
    session: AsyncSession, language_mode
) -> None:
    """Профиль отдаёт сохранённый язык, а не локаль Telegram.

    Режим ``all`` обязателен: в ``ru`` английский не входит в
    ``available_languages`` и ``resolve_language`` откатывает выбор назад.
    """
    language_mode("all")
    service = UserService(UserRepository(session))
    tg_id = 900000003
    user = await service.register(
        tg_id=tg_id,
        username=None,
        first_name="Профиль",
        last_name="",
        language_code="ru-RU",
        is_admin=False,
    )
    await service.set_language(tg_id, "en")
    await session.refresh(user)
    assert service.to_profile(user).language == "en"


async def test_catalog_hides_inactive_products(
    session: AsyncSession, unique_suffix: str
) -> None:
    """Скрытый товар не виден покупателю, но доступен админу."""
    product = await make_product(session, unique_suffix)
    repo = ProductRepository(session)
    service = ProductService(repo, PurchaseRepository(session))

    assert any(
        card.slug == product.slug for card in await service.list_catalog()
    )

    await repo.set_active(product, False)
    slugs = [card.slug for card in await service.list_catalog()]
    assert product.slug not in slugs

    with pytest.raises(ProductUnavailableError):
        await service.get_for_purchase(product.slug)

    assert (await service.get_any(product.slug)).slug == product.slug


async def test_purchase_grants_file_access(
    session: AsyncSession, unique_suffix: str, buyer
) -> None:
    """Право на файл появляется только после записи о покупке."""
    product = await make_product(session, unique_suffix)
    repo = ProductRepository(session)
    purchases = PurchaseRepository(session)
    service = ProductService(repo, purchases)
    order_id = await make_order(session, buyer.id, product)

    with pytest.raises(NotPurchasedError):
        await service.get_file_url_for_owner(buyer.id, product.id)

    await purchases.create(
        user_id=buyer.id, order_id=order_id, product_id=product.id
    )
    assert (
        await service.get_file_url_for_owner(buyer.id, product.id)
        == product.file_url
    )

    card = await service.get_for_purchase(product.slug)
    with pytest.raises(AlreadyPurchasedError):
        await service.require_not_owned(buyer.id, card)


async def test_purchase_listing_joins_products(
    session: AsyncSession, unique_suffix: str, buyer
) -> None:
    """«Мои покупки» отдают название и цену без второго запроса."""
    product = await make_product(session, unique_suffix)
    purchases = PurchaseRepository(session)
    order_id = await make_order(session, buyer.id, product)
    await purchases.create(
        user_id=buyer.id, order_id=order_id, product_id=product.id
    )
    service = ProductService(ProductRepository(session), purchases)
    rows = await service.list_purchases(buyer.id)
    assert rows
    assert rows[0].card.title == product.title
    assert rows[0].delivered is False


async def test_order_transition_is_atomic(
    session: AsyncSession, unique_suffix: str, buyer
) -> None:
    """Повторный переход из терминального статуса не проходит."""
    product = await make_product(session, unique_suffix)
    orders = OrderRepository(session)
    order = await orders.create(
        user_id=buyer.id,
        total_kopecks=product.price_kopecks,
        currency=product.currency,
        items_snapshot=snapshot_of(product),
    )
    assert await orders.transition(
        order.id,
        from_statuses=(OrderStatus.PENDING,),
        to=OrderStatus.AWAITING_PAYMENT,
    )
    assert not await orders.transition(
        order.id,
        from_statuses=(OrderStatus.PENDING,),
        to=OrderStatus.PAID,
    )
    assert await orders.transition(
        order.id,
        from_statuses=(OrderStatus.AWAITING_PAYMENT,),
        to=OrderStatus.PAID,
    )


async def test_mark_delivered_is_idempotent(
    session: AsyncSession, unique_suffix: str, buyer
) -> None:
    """Повторная выдача не меняет время первой доставки."""
    product = await make_product(session, unique_suffix)
    order_id = await make_order(session, buyer.id, product)
    purchases = PurchaseRepository(session)
    purchase = await purchases.create(
        user_id=buyer.id, order_id=order_id, product_id=product.id
    )
    first = await purchases.mark_delivered(purchase.id)
    assert first is not None and first.delivered_at is not None
    delivered_at = first.delivered_at

    second = await purchases.mark_delivered(purchase.id)
    assert second is not None
    assert second.delivered_at == delivered_at


async def test_payment_status_mapping_stored(
    session: AsyncSession, unique_suffix: str, buyer
) -> None:
    """Статус платежа сохраняется вместе с сырым ответом провайдера."""
    product = await make_product(session, unique_suffix)
    order = await OrderRepository(session).create(
        user_id=buyer.id,
        total_kopecks=product.price_kopecks,
        currency=product.currency,
        items_snapshot=snapshot_of(product),
    )
    payments = PaymentRepository(session)
    payment = await payments.create(
        order_id=order.id,
        provider=PaymentProvider.YOOKASSA,
        amount_kopecks=order.total_kopecks,
        currency=order.currency,
    )
    await payments.apply_provider_status(
        payment.id,
        status=PaymentStatus.SUCCEEDED,
        raw_response={"id": "pay-x", "status": "succeeded"},
    )
    await session.refresh(payment)
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.raw_response["status"] == "succeeded"
    assert payment.paid_at is not None


async def test_successful_sync_creates_purchase_once(
    session: AsyncSession, unique_suffix: str, buyer
) -> None:
    """Двойная проверка оплаты создаёт покупку ровно один раз.

    Это главная защита от выдачи товара дважды: кнопка «Проверить
    оплату» и webhook приходят в один и тот же ``_settle_order``.
    """
    product = await make_product(session, unique_suffix)
    orders = OrderRepository(session)
    payments = PaymentRepository(session)
    purchases = PurchaseRepository(session)
    order = await orders.create(
        user_id=buyer.id,
        total_kopecks=product.price_kopecks,
        currency=product.currency,
        items_snapshot=snapshot_of(product),
    )
    payment = await payments.create(
        order_id=order.id,
        amount_kopecks=order.total_kopecks,
        currency=order.currency,
    )
    provider_id = f"pay-{unique_suffix}"
    await payments.attach_provider_data(
        payment.id,
        provider_payment_id=provider_id,
        confirmation_url="https://pay.example/1",
        status=PaymentStatus.PENDING,
        raw_response={"id": provider_id},
    )
    succeeded = PaymentIntent(
        provider_payment_id=provider_id,
        status=PaymentStatus.SUCCEEDED,
        confirmation_url="https://pay.example/1",
        raw_response={"id": provider_id, "status": "succeeded"},
    )
    service = PaymentService(
        orders,
        payments,
        purchases,
        client_returning(succeeded, succeeded),
        return_url="https://shop.example/done",
    )

    assert await service.sync_payment_status(
        user_id=buyer.id, order_id=order.id
    )
    assert not await service.sync_payment_status(
        user_id=buyer.id, order_id=order.id
    )

    paid = await orders.get_with_relations(order.id)
    assert paid is not None and paid.status is OrderStatus.PAID
    assert len(await purchases.list_for_user(buyer.id)) == 1


async def test_delivery_items_and_confirmation(
    session: AsyncSession, unique_suffix: str, buyer
) -> None:
    """После подтверждения выдачи позиция исчезает из очереди отправки."""
    product = await make_product(session, unique_suffix)
    orders = OrderRepository(session)
    purchases = PurchaseRepository(session)
    order_id = await make_order(session, buyer.id, product)
    purchase = await purchases.create(
        user_id=buyer.id, order_id=order_id, product_id=product.id
    )
    service = PaymentService(
        orders,
        PaymentRepository(session),
        purchases,
        client_returning(),
        return_url="https://shop.example/done",
    )

    items = await service.delivery_items(user_id=buyer.id, order_id=order_id)
    assert [item.purchase_id for item in items] == [purchase.id]
    assert items[0].file_url == product.file_url

    await service.mark_delivered([purchase.id])
    assert await service.pending_purchases(order_id) == []
    assert not await service.delivery_items(user_id=buyer.id, order_id=order_id)
