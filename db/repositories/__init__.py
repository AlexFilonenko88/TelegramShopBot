"""Репозитории: единственный слой, где живут SQL-запросы."""

from db.repositories.base_repository import BaseRepository
from db.repositories.order_repository import OrderRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.product_repository import ProductRepository
from db.repositories.purchase_repository import PurchaseRepository
from db.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "OrderRepository",
    "PaymentRepository",
    "ProductRepository",
    "PurchaseRepository",
    "UserRepository",
]
