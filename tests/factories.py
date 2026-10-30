"""Заглушки Telegram-событий для тестов.

``model_construct`` не валидирует вложенные объекты, поэтому фильтры,
читающие ``chat`` или ``from_user``, работают, а сеть не нужна.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, Chat, Message, User

USER_ID = 5001


def user(user_id: int = USER_ID, language_code: str = "ru") -> User:
    """Отправитель события."""
    return User.model_construct(
        id=user_id,
        is_bot=False,
        first_name="Тест",
        language_code=language_code,
    )


def message_stub(text: str | None, user_id: int = USER_ID) -> Message:
    """Сообщение с реальными вложенными типами."""
    return Message.model_construct(
        message_id=1,
        date=datetime.now(UTC),
        text=text,
        chat=Chat.model_construct(id=user_id, type="private"),
        from_user=user(user_id),
    )


# Фильтрам нужен ``bot``: у Command он обязательный аргумент.
message_stub.bot = MagicMock(username="shopbot", id=42)  # type: ignore[attr-defined]


def callback_stub(data: str, user_id: int = USER_ID) -> CallbackQuery:
    """Нажатие inline-кнопки поверх сообщения-заглушки."""
    return CallbackQuery.model_construct(
        id="cb1",
        data=data,
        chat_instance="x",
        message=message_stub("/start", user_id),
        from_user=user(user_id),
    )


class FakeBot:
    """Бот-заглушка: методы ``send_message`` и др. только записываются."""

    def __init__(self) -> None:
        self.username = "shopbot"
        self.id = 42
        self.calls: list[tuple[str, Any]] = []
        self.session = MagicMock(close=AsyncMock())

    async def __call__(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        name = type(method).__name__
        self.calls.append((name, getattr(method, "text", "")))
        return True

    async def send_message(self, chat_id: int, text: str, **kw: Any) -> Any:
        self.calls.append(("send_message", text))
        return Message.model_construct(
            message_id=len(self.calls), date=datetime.now(UTC), text=text
        )

    async def answer_callback_query(self, *args: Any, **kw: Any) -> None:
        self.calls.append(("answer_callback_query", kw.get("text", "")))

    async def edit_message_text(self, *args: Any, **kw: Any) -> None:
        self.calls.append(("edit_message_text", kw.get("text", "")))
