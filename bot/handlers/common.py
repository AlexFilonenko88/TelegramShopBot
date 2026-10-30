"""Общие утилиты хендлеров.

Одно повторяющееся действие — «обновить сообщение с кнопками, а если
Telegram не дал — отправить новое». Вынесено сюда, чтобы каждый
inline-сценарий (каталог, карточка, заказ) не переписывал обработку
ошибки «message is not modified».
"""

from __future__ import annotations

import logging

from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


async def safe_edit(
    message: Message | None,
    text: str,
    markup: InlineKeyboardMarkup | None,
    *,
    resend: bool = True,
) -> None:
    """Редактирует сообщение или отправляет новое.

    Args:
        message: Сообщение под кнопками; ``None`` для старых кнопок,
            которые Telegram уже не отдаёт.
        text: Новый текст.
        markup: Новые кнопки (``None`` — убрать клавиатуру).
        resend: Отправлять дубль, если правка не удалась. Выключают там,
            где дублирование хуже пустого ответа.
    """
    if not isinstance(message, Message):
        if resend:
            logger.debug("Нет сообщения для правки — редактирование пропущено")
        return
    try:
        await message.edit_text(text, reply_markup=markup)
    except Exception as error:
        # «Message is not modified», «message to edit not found»,
        # устаревшие кнопки — всё это не сбой, а штатные ситуации.
        logger.debug("edit_text не удался (%s), отправляю новое", error)
        if resend:
            await message.answer(text, reply_markup=markup)
