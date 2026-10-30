"""Middleware локализации: определяет язык события один раз.

Язык считается по приоритету: сохранённый выбор пользователя > язык
клиента Telegram > значение из конфига (см. :func:`bot.i18n.resolve_language`).
Результат кладётся в контекст как ``language``, и хендлеры только
подставляют его в ``t(key, language, ...)`` — ни один обработчик не
должен сам решать, на каком языке отвечать.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.i18n import resolve_language
from bot.services.user_service import UserProfile


class I18nMiddleware(BaseMiddleware):
    """Добавляет ``language`` в контекст обработчика."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Вычисляет язык и передаёт его дальше.

        Args:
            handler: Следующий обработчик в цепочке.
            event: Входящий апдейт.
            data: Контекст обработчика.

        Returns:
            Результат обработчика.
        """
        profile: UserProfile | None = data.get("profile")
        tg_user = getattr(event, "from_user", None)
        client_language = tg_user.language_code if tg_user else None
        data["language"] = (
            profile.language
            if profile is not None
            else resolve_language(client_language, None)
        )
        return await handler(event, data)
