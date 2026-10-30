"""Reply-клавиатуры (главное меню под полем ввода).

Telegram возвращает для таких кнопок обычный текст, поэтому сопоставить
нажатие с действием можно только по подписи. Подписи локализованы, а
язык клиента может не совпадать с текущим языком бота (например, после
``/language``), поэтому разбор идёт по всем известным подписям.
"""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from bot.i18n import RUSSIAN, SUPPORTED_LANGUAGES, translate

MENU_ACTIONS: dict[str, str] = {
    "catalog": "menu.catalog",
    "purchases": "menu.my_purchases",
    "help": "menu.help",
}
"""Действие -> ключ подписи кнопки."""


def main_menu_keyboard(language: str = RUSSIAN) -> ReplyKeyboardMarkup:
    """Главное меню: каталог, покупки, помощь."""
    builder = ReplyKeyboardBuilder()
    for action in ("catalog", "purchases", "help"):
        builder.button(text=translate(MENU_ACTIONS[action], language))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def resolve_menu_action(text: str | None) -> str | None:
    """Определяет действие по тексту reply-кнопки.

    Args:
        text: Текст сообщения, пришедшего с клавиатуры.

    Returns:
        Ключ действия (``catalog`` | ``purchases`` | ``help``) или
        ``None``, если текст не похож на кнопку меню.
    """
    if not text:
        return None
    normalized = text.strip().lower()
    for language in SUPPORTED_LANGUAGES:
        for action, key in MENU_ACTIONS.items():
            if translate(key, language).strip().lower() == normalized:
                return action
    return None
