"""Middleware троттлинга — защиты от флуда.

Бот «дорогой» в реальном смысле: каждое обращение к YooKassa и каждый
запрос к БД стоят ресурсов. Пользователь может быстро наспамить кнопкой
«Купить», и тогда на его имя начнут создаваться дубли заказов.
Скользящее окно на отправителя отсекает такие события до того, как
откроется транзакция БД, — поэтому middleware стоит первым в цепочке.

Хранилище счётчиков — память процесса. Для одного инстанса (наш
контейнер) этого достаточно; при переходе на несколько воркеров
счётчики стоит вынести в Redis, ради этого логика лимита изолирована в
:class:`RateLimiter`.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.i18n import resolve_language, translate

DEFAULT_WINDOW_SECONDS = 5.0
DEFAULT_BURST = 6
"""Сколько событий подряд разрешено одному отправителю внутри окна."""

SWEEP_MIN_KEYS = 128
"""Не чистить словарь счётчиков, пока пользователей мало."""


class RateLimiter:
    """Скользящее окно «N событий за T секунд» на ключ."""

    def __init__(self, burst: int, window_seconds: float) -> None:
        """Args:
        burst: Разрешённое число событий внутри окна.
        window_seconds: Длина окна в секундах.
        """
        self._burst = max(1, burst)
        self._window = max(0.1, window_seconds)
        self._hits: dict[int, deque[float]] = {}

    @property
    def window_seconds(self) -> float:
        """Длина окна — нужна для текста подсказки."""
        return self._window

    def allow(self, key: int) -> bool:
        """Учитывает событие и говорит, разрешено ли оно.

        Args:
            key: Идентификатор ограничиваемого (Telegram ID).

        Returns:
            ``True``, если лимит не исчерпан; ``False`` — событие надо
            отклонить.
        """
        now = time.monotonic()
        cutoff = now - self._window
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self._burst:
            return False
        hits.append(now)
        self._sweep(cutoff)
        return True

    def _sweep(self, cutoff: float) -> None:
        """Забыть счётчики давно молчавших пользователей.

        Словарь живёт всё время работы бота, поэтому без чистки он рос бы
        вместе с числом когда-либо написавших людей. Окно grace в одно
        окно гарантирует, что активных отправителей чистка не заденет.
        """
        if len(self._hits) < SWEEP_MIN_KEYS:
            return
        stale = [
            key
            for key, hits in self._hits.items()
            if hits and hits[-1] < cutoff
        ]
        for key in stale:
            self._hits.pop(key, None)


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничивает частоту событий от одного пользователя."""

    def __init__(
        self,
        *,
        burst: int = DEFAULT_BURST,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        """Args:
        burst: Сколько событий разрешено подряд внутри окна.
        window_seconds: Длина скользящего окна в секундах.
        """
        self._limiter = RateLimiter(burst, window_seconds)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Пропускает событие или возвращает ответ «помедленнее».

        Args:
            handler: Следующий обработчик в цепочке.
            event: Входящий апдейт.
            data: Контекст обработчика.

        Returns:
            Результат обработчика либо объект Telegram-метода для
            отклонённого события — диспетчер отправит его сам.
        """
        user = getattr(event, "from_user", None)
        if user is None or self._limiter.allow(user.id):
            return await handler(event, data)
        return self._reject(event, user.language_code)

    def _reject(
        self, event: TelegramObject, client_language: str | None
    ) -> Any:
        """Формирует ответ «слишком часто» под тип события."""
        text = translate(
            "fsm.too_fast",
            resolve_language(client_language, None),
            seconds=round(self._limiter.window_seconds),
        )
        if isinstance(event, CallbackQuery):
            return AnswerCallbackQuery(
                callback_query_id=event.id,
                text=text,
                show_alert=False,
            )
        if isinstance(event, Message) and event.chat is not None:
            return SendMessage(chat_id=event.chat.id, text=text)
        return None
