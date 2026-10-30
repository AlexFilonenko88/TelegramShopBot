"""SQLAlchemy-модели проекта.

Импорты здесь гарантируют, что все таблицы зарегистрированы в
``Base.metadata`` — это критично для Alembic (``--autogenerate``) и
для создания схемы в тестах.
"""

from db.models.base import Base, TimestampMixin, enum_column
from db.models.enums import OrderStatus, PaymentProvider, PaymentStatus
from db.models.order import Order
from db.models.payment import Payment
from db.models.product import Product
from db.models.purchase import Purchase
from db.models.user import User

__all__ = [
    "Base",
    "Order",
    "OrderStatus",
    "Payment",
    "PaymentProvider",
    "PaymentStatus",
    "Product",
    "Purchase",
    "TimestampMixin",
    "User",
    "enum_column",
]
