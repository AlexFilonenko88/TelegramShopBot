"""Обработчики ошибок — последний рубеж перед «бот молчит».

Без них пользователь видел бы только «часики»: aiogram пишет исключение в
лог, а ответ в чат не уходит. Разделение намеренно простое: доменные
ошибки (:class:`ServiceError`) уже содержат безопасный для показа текст,
а инфраструктурные — нет, поэтому им отдаётся generic-подсказка, и только
в лог попадают подробности.

Сессию БД к этому моменту уже откатал и закрыл
:class:`bot.middlewares.db_retriever.DbSessionMiddleware`, поэтому здесь
нельзя обращаться к сервисам — только отвечать в Telegram.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    Message,
    TelegramObject,
    Update,
)

from bot.i18n import RUSSIAN, translate
from bot.services.errors import ServiceError

logger = logging.getLogger(__name__)


async def handle_service_error(
    event: ErrorEvent,
    exception: ServiceError,
    language: str = RUSSIAN,
) -> None:
    """Отвечает на доменную ошибку её же безопасным текстом.

    Args:
        event: Контекст aiogram: ``event.update`` — исходный апдейт.
        exception: Ошибка бизнес-слоя с готовой ``user_message``.
        language: Язык из ``I18nMiddleware``; если исключение поднялось
            раньше него, берётся язык по умолчанию.
    """
    logger.warning("Доменная ошибка: %s", exception.message)
    await _reply(_source_event(event.update), exception.user_message)


async def handle_telegram_api_error(
    event: ErrorEvent,
    exception: TelegramAPIError,
) -> None:
    """Гасит сбои самого Telegram API.

    Отвечать тем же сообщением на ошибку отправки — значит зациклиться,
    поэтому только пишем в лог.
    """
    logger.warning(
        "Telegram API отклонил запрос (%s): %s",
        type(_source_event(event.update)).__name__,
        exception,
    )


async def handle_unexpected_error(
    event: ErrorEvent,
    exception: Exception,
    language: str = RUSSIAN,
) -> None:
    """Логирует необработанное исключение и отвечает generic-подсказку.

    Текст намеренно обезличен: сообщения SQLAlchemy, aiohttp и aiogram
    содержат детали устройства системы (имена таблиц, URL, фрагменты
    заголовков) — показывать их пользователю нельзя.
    """
    logger.exception(
        "Необработанная ошибка при обработке %s",
        type(_source_event(event.update)).__name__,
        exc_info=exception,
    )
    await _reply(
        _source_event(event.update),
        translate("common.error", language),
    )


def _source_event(update: Update) -> TelegramObject | None:
    """Достаёт исходное событие из апдейта.

    ``ErrorEvent.update`` — это весь апдейт, а отвечать нужно конкретному
    сообщению или нажатию кнопки.
    """
    return update.callback_query or update.message


async def _reply(
    source: TelegramObject | Any,
    text: str,
) -> None:
    """Отвечает исходному событию, не порождая новых исключений.

    Args:
        source: Нажатие кнопки или сообщение (либо ``None``).
        text: Готовый текст ответа.
    """
    try:
        if isinstance(source, CallbackQuery):
            await source.answer(text, show_alert=True)
        elif isinstance(source, Message):
            await source.answer(text)
    except TelegramAPIError as error:
        # Пользователь заблокировал бота или сообщение удалено.
        logger.info("Не удалось ответить на ошибку: %s", error)


def register_error_handlers(router: Router) -> None:
    """Ставит обработчики ошибок в корневой роутер.

    Порядок важен: сначала узкий :class:`ServiceError`, затем сбой
    Telegram API, и лишь потом «всё остальное» — иначе generic-хендлер
    перехватит доменные ошибки и пользователь потеряет внятное сообщение.

    Args:
        router: Корневой роутер приложения.
    """
    router.errors.register(
        handle_service_error,
        ExceptionTypeFilter(ServiceError),
    )
    router.errors.register(
        handle_telegram_api_error,
        ExceptionTypeFilter(TelegramAPIError),
    )
    router.errors.register(handle_unexpected_error)
