"""Работа с денежными суммами.

Внутри проекта все суммы хранятся и считаются в целых копейках:
``Decimal``/``float`` для денег дают ошибки округления и рассинхрон с
YooKassa, где сумма — строка вида ``"1990.00"``.
"""

from __future__ import annotations

import re
from decimal import Decimal

KOPECKS_PER_RUBLE = 100
"""Пересчёт копеек в рубли."""

_AMOUNT_RE = re.compile(r"^\d{1,8}([.,]\d{1,2})?$")
"""Ввод цены: до 8 целых, не больше 2 знаков после разделителя."""


class InvalidAmountError(ValueError):
    """Введённую цену нельзя интерпретировать как деньги."""


def kopecks_to_str(kopecks: int) -> str:
    """Форматирует копейки как строку суммы для YooKassa.

    Args:
        kopecks: Сумма в копейках.

    Returns:
        Строка вида ``"1990.00"`` — обязательный формат ``amount.value``.
    """
    if kopecks < 0:
        raise ValueError(f"Сумма не может быть отрицательной: {kopecks}")
    rubles = Decimal(kopecks) / Decimal(KOPECKS_PER_RUBLE)
    return f"{rubles:.2f}"


def parse_price_to_kopecks(raw: str) -> int:
    """Разбирает human-friendly ввод цены в копейки.

    Принимает ``1990``, ``1990.50``, ``1990,5``, ``1 990,00``.

    Args:
        raw: Строка, введённая администратором.

    Returns:
        Сумма в копейках.

    Raises:
        InvalidAmountError: Если строка не похожа на деньги.
    """
    cleaned = raw.strip().replace(" ", "").replace("\u00a0", "")
    normalized = cleaned.replace(",", ".")
    if not _AMOUNT_RE.match(normalized):
        raise InvalidAmountError(
            f"Не понимаю цену {raw!r}: нужно число, например 1990 или 1990.50"
        )
    value = Decimal(normalized) * Decimal(KOPECKS_PER_RUBLE)
    return int(value.to_integral_value())


def format_price(kopecks: int, currency: str = "RUB") -> str:
    """Человекочитаемая цена для сообщений бота.

    Args:
        kopecks: Сумма в копейках.
        currency: Код валюты (ISO-4217).

    Returns:
        Строка вида ``"1 990,00 ₽"`` для рублей и ``"1 990,00 RUB"``
        для прочих валют.
    """
    rubles = Decimal(kopecks) / Decimal(KOPECKS_PER_RUBLE)
    formatted = f"{rubles:,.2f}".replace(",", " ").replace(".", ",")
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(currency, currency)
    return f"{formatted} {symbol}"
