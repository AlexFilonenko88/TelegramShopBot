"""Репозиторий товаров."""

from __future__ import annotations

from sqlalchemy import select

from db.models.product import Product
from db.repositories.base_repository import BaseRepository


class ProductRepository(BaseRepository[Product]):
    """CRUD-операции над :class:`Product`."""

    model = Product

    async def get_active(self) -> list[Product]:
        """Возвращает активные товары (пагинация не нужна: каталог мал)."""
        stmt = (
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.id)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_by_slug(self, slug: str) -> Product | None:
        """Возвращает активный товар по slug или ``None``.

        Скрытый товар покупателю недоступен, поэтому фильтр по
        ``is_active`` здесь обязателен.
        """
        stmt = select(Product).where(
            Product.slug == slug,
            Product.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_any_by_slug(self, slug: str) -> Product | None:
        """Товар по slug без учёта видимости (админские операции)."""
        stmt = select(Product).where(Product.slug == slug)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        """Занят ли slug (для генерации уникального при коллизии)."""
        stmt = select(Product.id).where(Product.slug == slug).limit(1)
        return (
            await self.session.execute(stmt)
        ).scalar_one_or_none() is not None

    async def list_all(self, *, include_hidden: bool = True) -> list[Product]:
        """Список товаров для админ-команды ``/products``."""
        stmt = select(Product)
        if not include_hidden:
            stmt = stmt.where(Product.is_active.is_(True))
        stmt = stmt.order_by(Product.id)
        return list((await self.session.scalars(stmt)).all())

    async def set_active(self, product: Product, is_active: bool) -> Product:
        """Ставит товар в продажу или снимает с неё."""
        product.is_active = is_active
        await self.session.flush()
        return product

    async def set_price(self, product: Product, price_kopecks: int) -> Product:
        """Меняет цену товара в копейках."""
        product.price_kopecks = price_kopecks
        await self.session.flush()
        return product

    async def create_product(
        self,
        *,
        title: str,
        description: str,
        price_kopecks: int,
        file_url: str,
        slug: str,
    ) -> Product:
        """Создаёт новый товар.

        Args:
            title: Название товара.
            description: Полное описание.
            price_kopecks: Цена в копейках (целое число).
            file_url: Внутренняя ссылка на файл товара.
            slug: Стабильный идентификатор для deep-link ссылок.

        Returns:
            Созданный товар.
        """
        product = Product(
            title=title,
            description=description,
            price_kopecks=price_kopecks,
            file_url=file_url,
            slug=slug,
        )
        self.session.add(product)
        await self.session.flush()
        return product

    async def count_active(self) -> int:
        """Число товаров в продаже (для админской сводки)."""
        stmt = select(Product.id).where(Product.is_active.is_(True))
        return len((await self.session.scalars(stmt)).all())
