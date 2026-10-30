"""Репозиторий пользователей."""

from __future__ import annotations

from sqlalchemy import select

from db.models.user import User
from db.repositories.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """CRUD-операции над :class:`User`."""

    model = User

    async def get_by_tg_id(self, tg_id: int) -> User | None:
        """Ищет пользователя по Telegram ID (он же первичный ключ)."""
        return await self.session.get(User, tg_id)

    async def upsert(
        self,
        tg_id: int,
        *,
        username: str | None,
        first_name: str,
        last_name: str,
        language_code: str,
        is_admin: bool,
    ) -> User:
        """Создаёт пользователя или обновляет его профиль.

        Права администратора пересчитываются каждый раз: если ID убрали
        из ``ADMIN_IDS``, человек теряет доступ к админ-командам.

        Args:
            tg_id: Telegram ID пользователя.
            username: ``@username`` либо ``None``.
            first_name: Имя из Telegram.
            last_name: Фамилия из Telegram.
            language_code: Язык интерфейса клиента Telegram.
            is_admin: Администратор ли (по ``ADMIN_IDS`` из конфига).

        Returns:
            Актуальная запись пользователя.
        """
        user = await self.session.get(User, tg_id)
        if user is None:
            user = User(
                id=tg_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                is_admin=is_admin,
            )
            self.session.add(user)
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.language_code = language_code
            user.is_admin = is_admin
            user.is_active = True
        await self.session.flush()
        return user

    async def set_preferred_language(self, user: User, language: str) -> User:
        """Запоминает выбор языка, сделанный пользователем в боте.

        Отдельное поле нужно потому, что ``language_code`` Telegram
        перезаписывается на каждом событии: без него выбор пользователя
        терялся бы при смене языка клиента.

        Args:
            user: Найденная запись пользователя.
            language: Код языка из поддерживаемых.

        Returns:
            Та же запись с обновлённым полем.
        """
        user.preferred_language = language
        await self.session.flush()
        return user

    async def list_active_ids(self) -> list[int]:
        """Возвращает ID всех активных пользователей (для рассылок)."""
        stmt = select(User.id).where(User.is_active.is_(True)).order_by(User.id)
        return list((await self.session.scalars(stmt)).all())

    async def count_active(self) -> int:
        """Число активных пользователей (для админской сводки)."""
        stmt = select(User.id).where(User.is_active.is_(True))
        return len((await self.session.scalars(stmt)).all())
