"""Фабрики callback-данных для inline-кнопок.

aiogram 3.x хранит ``callback_data`` строкой до 64 байт. Ручной разбор
вида ``buy:slug:page`` хрупок, поэтому каждая кнопка описана pydantic-
моделью :class:`aiogram.filters.callback_data.CallbackData`: packing и
валидация на входе становятся автоматическими, а чужие/битые данные
просто не проходят фильтр.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class NavCallback(CallbackData, prefix="nav"):
    """Навигация по разделам без аргументов (``/catalog``, «помощь»).

    Attributes:
        action: Имя раздела: ``catalog`` | ``my_purchases`` | ``help`` |
            ``back_menu``.
    """

    action: str


class ProductCallback(CallbackData, prefix="prod"):
    """Действия над конкретным товаром.

    Attributes:
        action: ``open`` (карточка) | ``buy`` (оформить заказ) |
            ``get_file`` (выдать материалы) | ``hide`` | ``show``
            (админ: снять/вернуть в продажу) | ``edit_price`` (админ).
        slug: Идентификатор товара; пустой — для списков без выбора.
    """

    action: str
    slug: str = ""


class OrderCallback(CallbackData, prefix="order"):
    """Управление заказом и платежом.

    Attributes:
        action: ``confirm`` (создать счёт) | ``check_payment``
            (переспросить провайдера) | ``cancel`` | ``repeat_delivery``
            (повторно выдать файлы) | ``details``.
        order_id: ID заказа из ``orders.id``.
    """

    action: str
    order_id: int = 0


class PageCallback(CallbackData, prefix="page"):
    """Постраничная навигация каталога.

    Attributes:
        action: ``prev`` | ``next``.
        page: Номер страницы (0-based).
    """

    action: str
    page: int = 0


class AdminCallback(CallbackData, prefix="adm"):
    """Админские действия, в том числе выбор товара.

    Attributes:
        action: ``products`` | ``add_product`` | ``broadcast`` |
            ``stats`` | ``edit`` (открыть карточку управления товаром).
        payload: slug товара для ``edit``; пусто для остальных действий.
    """

    action: str
    payload: str = ""


class ConfirmChoiceCallback(CallbackData, prefix="cfm"):
    """Подтверждение или отмена шага FSM-опроса.

    Attributes:
        target: Что подтверждаем: ``create_product`` | ``broadcast`` |
            ``toggle_active``.
        approved: Результат выбора пользователя.
        payload: Дополнительные данные (slug товара, номер заказа).
    """

    target: str
    approved: bool
    payload: str = ""
