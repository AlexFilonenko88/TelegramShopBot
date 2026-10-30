"""Тесты денежного модуля: только чистые функции, без БД."""

from decimal import Decimal

import pytest
from bot.services.money import (
    InvalidAmountError,
    format_price,
    kopecks_to_str,
    parse_price_to_kopecks,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1990", 199000),
        ("1990.50", 199050),
        ("1990,5", 199050),
        ("1 990,00", 199000),
        ("1\u00a0990", 199000),
        ("0", 0),
        ("0.01", 1),
        ("  2500  ", 250000),
    ],
)
def test_parse_price_accepts_human_input(raw: str, expected: int) -> None:
    """Форматы, которые админ реально вводит с телефона."""
    assert parse_price_to_kopecks(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "дорого", "1.234", "12,345", "-100", "1990.", "1e5"],
)
def test_parse_price_rejects_garbage(raw: str) -> None:
    """Мусорный ввод не должен превращаться в цену."""
    with pytest.raises(InvalidAmountError):
        parse_price_to_kopecks(raw)


def test_parse_price_strips_grouping_spaces() -> None:
    """Пробелы считаются разделителями разрядов, а не текстом."""
    assert parse_price_to_kopecks("12 34 56") == 12345600


def test_parse_price_handles_upper_bound() -> None:
    """8 целых разрядов — предел; 9 уже отвергаются."""
    assert parse_price_to_kopecks("99999999.99") == 9999999999
    with pytest.raises(InvalidAmountError):
        parse_price_to_kopecks("100000000")


@pytest.mark.parametrize(
    ("kopecks", "expected"),
    [
        (199000, "1990.00"),
        (0, "0.00"),
        (1, "0.01"),
        (9999999999, "99999999.99"),
    ],
)
def test_kopecks_to_str_matches_yookassa_format(
    kopecks: int, expected: str
) -> None:
    """YooKassa ждёт строку с двумя знаками: float дал бы 1990.0."""
    assert kopecks_to_str(kopecks) == expected


def test_kopecks_to_str_rejects_negative() -> None:
    """Отрицательная сумма — ошибка программиста, а не пользователя."""
    with pytest.raises(ValueError):
        kopecks_to_str(-1)


@pytest.mark.parametrize(
    ("kopecks", "currency", "expected"),
    [
        (199000, "RUB", "1 990,00 ₽"),
        (199050, "RUB", "1 990,50 ₽"),
        (100, "USD", "1,00 $"),
        (100, "KZT", "1,00 KZT"),
    ],
)
def test_format_price_uses_locale_separators(
    kopecks: int, currency: str, expected: str
) -> None:
    """Русская запись: пробел между разрядами, запятая в дробях."""
    assert format_price(kopecks, currency) == expected


def test_money_roundtrip_keeps_value() -> None:
    """Парсинг ввода и вывод обратно не теряют копейки."""
    for raw in ("1990", "1990,50", "0.01", "99999999.99"):
        kopecks = parse_price_to_kopecks(raw)
        restored = Decimal(kopecks_to_str(kopecks)) * 100
        assert int(restored) == kopecks
