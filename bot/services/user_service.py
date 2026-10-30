"""Бизнес-логика пользователей.

Единая точка входа для «кто этот человек»: регистрация по первому
сообщению, определение языка, проверка прав администратора. Handlers
не знают про репозитории и обращаются только сюда.
"""

from __future__ import annotations

from dataclasses import dataclass

from db.models.user import User
from db.repositories.user_repository import UserRepository

from bot.i18n import resolve_language
from bot.services.errors import PermissionDeniedError, UserNotFoundError


@dataclass(frozen=True)
class UserProfile:
    """Снимок профиля, передаваемый в контекст обработчиков.

    Attributes:
        tg_id: Telegram ID (он же первичный ключ в БД).
        language: Язык интерфейса, выбранный для пользователя.
        is_admin: Есть ли права администратора.
        display_name: Имя для обращения в текстах.
    """

    tg_id: int
    language: str
    is_admin: bool
    display_name: str

    @property
    def mention(self) -> str:
        """Строка для логов и админ-уведомлений."""
        return f"{self.display_name} (id={self.tg_id})"


class UserService:
    """Работа с профилем пользователя."""

    def __init__(self, users: UserRepository) -> None:
        """Args: users: Репозиторий пользователей (сессия внутри)."""
        self._users = users

    async def register(
        self,
        *,
        tg_id: int,
        username: str | None,
        first_name: str,
        last_name: str,
        language_code: str,
        is_admin: bool,
    ) -> User:
        """Создаёт пользователя или обновляет данные существующего.

        Вызывается из middleware на каждом сообщении, поэтому профиль в
        БД всегда актуален (имя и язык могли измениться в Telegram).

        Args:
            tg_id: Telegram ID.
            username: ``@username`` либо ``None``.
            first_name: Имя из Telegram.
            last_name: Фамилия из Telegram.
            language_code: Язык клиента (``ru``, ``en`` ...).
            is_admin: Права администратора из ``ADMIN_IDS``.

        Returns:
            Запись пользователя.
        """
        return await self._users.upsert(
            tg_id=tg_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            is_admin=is_admin,
        )

    async def set_language(self, tg_id: int, language: str) -> User:
        """Запоминает выбор языка пользователем.

        Args:
            tg_id: Telegram ID.
            language: Код языка из поддерживаемых.

        Returns:
            Обновлённая запись пользователя.

        Raises:
            UserNotFoundError: Пользователь не зарегистрирован.
        """
        user = await self._users.get_by_tg_id(tg_id)
        if user is None:
            raise UserNotFoundError(tg_id)
        return await self._users.set_preferred_language(user, language)

    async def get_profile(self, tg_id: int) -> UserProfile:
        """Возвращает профиль по Telegram ID.

        Args:
            tg_id: Telegram ID.

        Returns:
            Снимок профиля для обработчика.

        Raises:
            UserNotFoundError: Если пользователя нет в БД — значит
                он не прошёл регистрацию через middleware.
        """
        user = await self._users.get_by_tg_id(tg_id)
        if user is None:
            raise UserNotFoundError(tg_id)
        return self.to_profile(user)

    def to_profile(self, user: User) -> UserProfile:
        """Превращает ORM-объект в безопасный для контекста снимок.

        Профиль — dataclass без ссылки на сессию: его можно положить в
        ``data`` aiogram, не удерживая сессию живой. Язык считается здесь
        же, чтобы хендлеры просто брали ``profile.language``.
        """
        return UserProfile(
            tg_id=user.id,
            language=resolve_language(
                user.language_code, user.preferred_language
            ),
            is_admin=user.is_admin,
            display_name=user.first_name or user.username or str(user.id),
        )

    async def require_admin(self, tg_id: int) -> UserProfile:
        """Проверяет права администратора.

        Args:
            tg_id: Telegram ID.

        Returns:
            Профиль администратора.

        Raises:
            UserNotFoundError: Пользователь не зарегистрирован.
            PermissionDeniedError: Прав администратора нет.
        """
        profile = await self.get_profile(tg_id)
        if not profile.is_admin:
            raise PermissionDeniedError(f"доступ пользователя {tg_id}")
        return profile

    async def active_user_ids(self) -> list[int]:
        """Список ID активных пользователей (для рассылок)."""
        return await self._users.list_active_ids()

    async def count_active(self) -> int:
        """Число активных пользователей (для сводки ``/stats``)."""
        return await self._users.count_active()
