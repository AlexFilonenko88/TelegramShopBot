"""Бизнес-логика каталога цифровых товаров.

Отвечает за показ витрины, проверку права на выдачу файлов и админские
операции над позициями. SQL-запросов нет — только репозитории.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from db.models.product import Product
from db.repositories.product_repository import ProductRepository
from db.repositories.purchase_repository import PurchaseRepository

from bot.services.errors import (
    AlreadyPurchasedError,
    NotPurchasedError,
    ProductUnavailableError,
)
from bot.services.money import format_price, parse_price_to_kopecks

SLUG_MAX_LENGTH = 48
"""Длина slug: остаётся запас под суффикс при коллизии."""

TRANSLIT_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
"""Транслитерация кириллицы: товары для СНГ называются по-русски, а в
URL и callback-данных должны оставаться только ASCII-символы."""


@dataclass(frozen=True)
class ProductCard:
    """Товар в виде, безопасном для показа в чате.

    ``file_url`` здесь сознательно отсутствует: ссылку на материалы
    получает только владелец покупки, иначе товар скачали бы без оплаты.
    """

    id: int
    slug: str
    title: str
    description: str
    price_kopecks: int
    currency: str

    @classmethod
    def from_model(cls, product: Product) -> ProductCard:
        """Строит карточку из ORM-объекта."""
        return cls(
            id=product.id,
            slug=product.slug,
            title=product.title,
            description=product.description,
            price_kopecks=product.price_kopecks,
            currency=product.currency,
        )

    @property
    def formatted_price(self) -> str:
        """Цена в человекочитаемом виде для текста сообщения."""
        return format_price(self.price_kopecks, self.currency)


@dataclass(frozen=True)
class PurchaseInfo:
    """Запись истории покупок для раздела «Мои покупки».

    Attributes:
        purchase_id: ID покупки (нужен для подтверждения выдачи).
        order_id: Заказ, по которому покупка выдана — по нему работает
            «повторить выдачу».
        delivered: Отправлены ли материалы (``delivered_at`` проставлен).
        card: Карточка товара без ``file_url`` — ссылку выдаёт отдельный
            запрос с проверкой владельца.
    """

    purchase_id: int
    order_id: int
    delivered: bool
    card: ProductCard

    @property
    def formatted_price(self) -> str:
        """Цена товара в текущем виде для строки истории."""
        return self.card.formatted_price


def build_slug(title: str) -> str:
    """Делает из названия товара URL-safe slug.

    Args:
        title: Название товара (может быть на кириллице).

    Returns:
        Строка вида ``kurs-po-python``; если букв нет — ``product``.
    """
    normalized = unicodedata.normalize("NFKC", title).lower()
    latin = "".join(TRANSLIT_MAP.get(ch, ch) for ch in normalized)
    decomposed = unicodedata.normalize("NFKD", latin)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return cleaned[:SLUG_MAX_LENGTH].strip("-") or "product"


class ProductService:
    """Витрина и администрирование товаров."""

    def __init__(
        self,
        products: ProductRepository,
        purchases: PurchaseRepository,
    ) -> None:
        """Args:
        products: Репозиторий товаров.
        purchases: Репозиторий покупок (проверка права на выдачу).
        """
        self._products = products
        self._purchases = purchases

    async def list_catalog(self) -> list[ProductCard]:
        """Активные товары для клавиатуры каталога."""
        return [
            ProductCard.from_model(product)
            for product in await self._products.get_active()
        ]

    async def get_for_purchase(self, slug: str) -> ProductCard:
        """Товар по slug для начала оформления заказа.

        Args:
            slug: Идентификатор из callback-данных кнопки.

        Returns:
            Карточка товара.

        Raises:
            ProductUnavailableError: Товар снят с продажи или не найден.
        """
        product = await self._products.get_by_slug(slug)
        if product is None:
            raise ProductUnavailableError(slug)
        return ProductCard.from_model(product)

    async def require_not_owned(
        self, user_id: int, product: ProductCard
    ) -> None:
        """Запрещает повторно покупать уже купленный товар.

        Args:
            user_id: Telegram ID покупателя.
            product: Товар, который пытаются купить.

        Raises:
            AlreadyPurchasedError: Покупка уже оформлена.
        """
        if await self._purchases.has_purchase(user_id, product.id):
            raise AlreadyPurchasedError(product.slug)

    async def get_file_url_for_owner(
        self, user_id: int, product_id: int
    ) -> str:
        """Ссылка на материалы — только владельцу покупки.

        Args:
            user_id: Telegram ID покупателя.
            product_id: ID товара.

        Returns:
            ``file_url`` товара.

        Raises:
            ProductUnavailableError: Товара нет в каталоге.
            NotPurchasedError: Пользователь товар не покупал.
        """
        product = await self._products.get_by_id(product_id)
        if product is None:
            raise ProductUnavailableError(f"id={product_id}")
        if not await self._purchases.has_purchase(user_id, product_id):
            raise NotPurchasedError(user_id, product_id)
        return product.file_url

    async def create_product(
        self,
        *,
        title: str,
        description: str,
        price_raw: str,
        file_url: str,
    ) -> Product:
        """Создаёт товар (админ-команда ``/add_product``).

        Args:
            title: Название.
            description: Описание для карточки.
            price_raw: Цена в human-friendly виде (``1990,50``).
            file_url: Ссылка на материалы.

        Returns:
            Созданный товар.

        Raises:
            InvalidAmountError: Цену нельзя разобрать.
            ValueError: Пустое название или пустая ссылка.
        """
        if not title.strip():
            raise ValueError("Название не может быть пустым")
        if not file_url.strip():
            raise ValueError("Ссылка на файл не может быть пустой")
        price_kopecks = parse_price_to_kopecks(price_raw)
        slug = await self._unique_slug(build_slug(title))
        return await self._products.create_product(
            title=title.strip(),
            description=description.strip(),
            price_kopecks=price_kopecks,
            file_url=file_url.strip(),
            slug=slug,
        )

    async def set_active(self, slug: str, is_active: bool) -> Product:
        """Ставит товар в продажу или снимает с неё.

        Raises:
            ProductUnavailableError: Товар не найден (даже скрытый).
        """
        product = await self._products.get_any_by_slug(slug)
        if product is None:
            raise ProductUnavailableError(slug)
        return await self._products.set_active(product, is_active)

    async def update_price(self, slug: str, price_raw: str) -> Product:
        """Меняет цену товара.

        Уже созданные заказы не затрагиваются: их сумма зафиксирована в
        ``orders.total_kopecks`` и ``items_snapshot`` на момент оформления.

        Raises:
            ProductUnavailableError: Товар не найден.
            InvalidAmountError: Цену нельзя разобрать.
        """
        product = await self._products.get_any_by_slug(slug)
        if product is None:
            raise ProductUnavailableError(slug)
        return await self._products.set_price(
            product, parse_price_to_kopecks(price_raw)
        )

    async def list_all(self, *, include_hidden: bool = True) -> list[Product]:
        """Полный список для админ-команды ``/products``."""
        return await self._products.list_all(include_hidden=include_hidden)

    async def get_any(self, slug: str) -> Product:
        """Товар по slug, включая снятый с продажи — для админских нужд.

        Raises:
            ProductUnavailableError: Товара нет вообще.
        """
        product = await self._products.get_any_by_slug(slug)
        if product is None:
            raise ProductUnavailableError(slug)
        return product

    @staticmethod
    def parse_price(raw: str) -> int:
        """Разбирает human-friendly ввод цены в копейки.

        Вынесен как статический метод, чтобы админ-хендлер мог
        проверить валидность до сохранения в FSM-данные.

        Raises:
            InvalidAmountError: Цену нельзя разобрать.
        """
        return parse_price_to_kopecks(raw)

    async def count_active(self) -> int:
        """Число товаров в продаже (для сводки ``/stats``)."""
        return await self._products.count_active()

    async def list_purchases(self, user_id: int) -> list[PurchaseInfo]:
        """История покупок пользователя для раздела «Мои покупки».

        Args:
            user_id: Telegram ID покупателя.

        Returns:
            Записи от новых к старым; цены берутся из текущих цен
            товара, а из заказа сумма не восстанавливается.
        """
        rows = await self._purchases.list_with_products(user_id=user_id)
        return [
            PurchaseInfo(
                purchase_id=purchase.id,
                order_id=purchase.order_id,
                delivered=purchase.delivered_at is not None,
                card=ProductCard.from_model(product),
            )
            for purchase, product in rows
        ]

    async def _unique_slug(self, base: str) -> str:
        """Подбирает свободный slug, добавляя суффикс при коллизии.

        Args:
            base: Желаемый slug, построенный из названия.

        Returns:
            Уникальный в рамках таблицы slug.
        """
        candidate = base
        suffix = 2
        while await self._products.slug_exists(candidate):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate
