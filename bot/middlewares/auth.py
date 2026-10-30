"""Middleware аутентификации: «кто говорит с ботом».

Telegram не даёт гарантию, что пользователь уже в базе: первое же
сообщение (или ``/start``) приходит от незнакомца. Поэтому на каждом
событии профиль апсейртится, а обработчики получают готовый
:class:`UserProfile` и флаг администратора.

Права читаются только отсюда: ``ADMIN_IDS`` — единственный источник
истины, и пересчёт происходит на каждом событии, так что отзыв доступа
действует сразу, без перезапуска бота.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from bot.services.user_service import UserService


class AuthMiddleware(BaseMiddleware):
    """Регистрирует отправителя и кладёт его профиль в контекст."""

    def __init__(self, is_admin_checker: Callable[[int], bool]) -> None:
        """Args:
        is_admin_checker: Функция «является ли id администратором»
            (в ``main`` это проверка против ``settings.is_admin``).
        """
        self._is_admin = is_admin_checker

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Апсейртит пользователя и добавляет ``profile``/``tg_id``.

        Args:
            handler: Следующий обработчик в цепочке.
            event: Входящий апдейт.
            data: Контекст обработчика.

        Returns:
            Результат обработчика. События без отправителя (например,
            служебные уведомления о чатах) проходят дальше без профиля.
        """
        user: User | None = getattr(event, "from_user", None)
        if user is None or "user_service" not in data:
            return await handler(event, data)

        service: UserService = data["user_service"]
        stored = await service.register(
            tg_id=user.id,
            username=user.username,
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            language_code=user.language_code or "",
            is_admin=self._is_admin(user.id),
        )
        data["tg_id"] = user.id
        data["profile"] = service.to_profile(stored)
        return await handler(event, data)
