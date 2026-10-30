"""FSM-состояния диалогов бота.

Каждая группа состояний соответствует одному пошаговому сценарию
(аналог ``StatesGroup`` из aiogram 3.x). Состояния используются и как
фильтры в хендлерах, и как «якорь» для middleware сессии.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ShopStates(StatesGroup):
    """Покупка: выбор товара -> подтверждение -> оплата."""

    choosing_product = State()
    confirming_order = State()
    awaiting_payment = State()


class ProductFormStates(StatesGroup):
    """Админское добавление товара пошаговым опросом.

    Поля собираются по очереди, потому что описание и ссылка на файл
    не влазят в одну команду ``/add_product`` и легко ломают парсинг.
    """

    waiting_title = State()
    waiting_description = State()
    waiting_price = State()
    waiting_file_url = State()
    confirming = State()


class ProductEditStates(StatesGroup):
    """Админское редактирование цены/описания существующего товара."""

    choosing_product = State()
    waiting_value = State()


class BroadcastStates(StatesGroup):
    """Админская рассылка сообщения всем активным пользователям."""

    waiting_message = State()
    confirming = State()
