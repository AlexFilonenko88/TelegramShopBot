"""Тесты клавиатур: разбиение на страницы и состав кнопок.

Регресс, который здесь закреплён: ``builder.adjust()`` пересобирает все
кнопки в плоский список, поэтому каталог собирает ряды вручную — иначе
навигация «⬅️ 1/3 ➡️» разваливалась на три отдельные строки.
"""

import pytest
from bot.i18n import RUSSIAN, translate
from bot.keyboards.callback_data import NavCallback, ProductCallback
from bot.keyboards.inline import (
    CATALOG_PAGE_SIZE,
    catalog_keyboard,
    delivery_keyboard,
    language_keyboard,
    product_keyboard,
)
from bot.services.product_service import ProductCard


def card(index: int, slug: str | None = None) -> ProductCard:
    """Товар-заглушка с предсказуемыми полями."""
    return ProductCard(
        id=index,
        slug=slug or f"tovar-{index}",
        title=f"Товар {index}",
        description="Описание",
        price_kopecks=100000 + index,
        currency="RUB",
    )


def test_catalog_single_page_has_no_navigation() -> None:
    """При одной странице стрелки не нужны — только товары и «Назад»."""
    keyboard = catalog_keyboard([card(1)], RUSSIAN)
    rows = keyboard.inline_keyboard
    assert len(rows) == 2
    assert rows[-1][0].callback_data == NavCallback(action="back_menu").pack()


def test_catalog_paginates_by_page_size() -> None:
    """На странице ровно ``CATALOG_PAGE_SIZE`` товаров."""
    products = [card(i) for i in range(1, CATALOG_PAGE_SIZE * 2 + 1)]
    first = catalog_keyboard(products, RUSSIAN, page=0)
    assert len(first.inline_keyboard) == CATALOG_PAGE_SIZE + 2

    second = catalog_keyboard(products, RUSSIAN, page=1)
    titles = [row[0].text for row in second.inline_keyboard[:CATALOG_PAGE_SIZE]]
    assert all("Товар" in title for title in titles)
    assert "Товар 1 " not in titles[0]


def test_catalog_navigation_row_is_flat() -> None:
    """Кнопки навигации стоят в одном ряду: 1/2, а не три ряда."""
    products = [card(i) for i in range(1, CATALOG_PAGE_SIZE + 2)]
    keyboard = catalog_keyboard(products, RUSSIAN, page=1)
    nav_row = keyboard.inline_keyboard[-2]
    assert len(nav_row) == 2
    labels = [button.text for button in nav_row]
    assert "⬅️" in labels
    assert any("/" in label for label in labels)


def test_catalog_first_page_has_no_back_arrow() -> None:
    """На первой странице стрелка «назад» бессмысленна."""
    products = [card(i) for i in range(1, CATALOG_PAGE_SIZE + 2)]
    keyboard = catalog_keyboard(products, RUSSIAN, page=0)
    labels = [button.text for button in keyboard.inline_keyboard[-2]]
    assert "⬅️" not in labels
    assert "➡️" in labels


def test_catalog_last_page_has_no_forward_arrow() -> None:
    """На последней — нет «вперёд»."""
    products = [card(i) for i in range(1, CATALOG_PAGE_SIZE + 2)]
    keyboard = catalog_keyboard(products, RUSSIAN, page=1)
    labels = [button.text for button in keyboard.inline_keyboard[-2]]
    assert "➡️" not in labels


def test_catalog_empty_page_keeps_back_button() -> None:
    """Пустая страница (после скрытия товара) не оставляет без выхода."""
    keyboard = catalog_keyboard([], RUSSIAN, page=5)
    assert keyboard.inline_keyboard[-1][0].callback_data == (
        NavCallback(action="back_menu").pack()
    )


def test_catalog_button_opens_product() -> None:
    """Кнопка товара несёт действие ``open`` и slug."""
    keyboard = catalog_keyboard([card(1, "kurs")], RUSSIAN)
    parsed = ProductCallback.unpack(
        keyboard.inline_keyboard[0][0].callback_data
    )
    assert parsed.action == "open"
    assert parsed.slug == "kurs"


def test_long_title_is_clipped() -> None:
    """Telegram ограничивает подпись кнопки — длинные названия режем."""
    long_card = card(1, "long")
    long_card = ProductCard(
        id=1,
        slug="long",
        title="Очень длинное название товара " * 5,
        description="",
        price_kopecks=100,
        currency="RUB",
    )
    keyboard = catalog_keyboard([long_card], RUSSIAN)
    assert len(keyboard.inline_keyboard[0][0].text) <= 64


def test_product_keyboard_offers_buy_when_not_owned() -> None:
    """Непокупленный товар: кнопка «Купить»."""
    keyboard = product_keyboard(card(1, "kurs"), RUSSIAN, owned=False)
    actions = [
        ProductCallback.unpack(button.callback_data).action
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("prod:")
    ]
    assert actions == ["buy"]


def test_product_keyboard_offers_download_when_owned() -> None:
    """Купленный товар: кнопка выдачи файла вместо повторной продажи."""
    keyboard = product_keyboard(card(1, "kurs"), RUSSIAN, owned=True)
    actions = [
        ProductCallback.unpack(button.callback_data).action
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("prod:")
    ]
    assert actions == ["get_file"]


def test_delivery_keyboard_contains_file_link() -> None:
    """Ссылка на файл отдаётся как URL-кнопка."""
    keyboard = delivery_keyboard("https://files.example/a.pdf", RUSSIAN)
    urls = [
        button.url
        for row in keyboard.inline_keyboard
        for button in row
        if button.url
    ]
    assert urls == ["https://files.example/a.pdf"]


def test_language_keyboard_marks_current_choice(monkeypatch) -> None:
    """Текущий язык помечен, иначе пользователь не поймёт, что выбрано.

    Список языков берётся из конфига, а в ``.env`` обычно включён только
    русский — для теста открываем оба.
    """
    from types import SimpleNamespace

    from bot import i18n

    monkeypatch.setattr(
        i18n,
        "get_settings",
        lambda: SimpleNamespace(bot_language_mode="all", default_language="ru"),
    )
    keyboard = language_keyboard("en")
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert len(labels) == 2
    marked = [label for label in labels if label.startswith("✓")]
    assert len(marked) == 1
    assert "English" in marked[0]


@pytest.mark.parametrize("language", [RUSSIAN, "en"])
def test_all_buttons_have_text(language: str) -> None:
    """Пустая подпись — ошибка локализации, её видно сразу."""
    keyboard = catalog_keyboard([card(1)], language)
    for row in keyboard.inline_keyboard:
        for button in row:
            assert button.text.strip()
    assert translate("menu.back", language) != "menu.back"
