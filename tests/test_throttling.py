"""Тесты троттлинга: скользящее окно и ответы на отказ."""

from aiogram.methods import AnswerCallbackQuery, SendMessage
from bot.middlewares.throttling import RateLimiter, ThrottlingMiddleware

from tests.factories import callback_stub, message_stub


def test_limiter_allows_up_to_burst() -> None:
    """Внутри окна проходит ровно ``burst`` событий."""
    limiter = RateLimiter(burst=3, window_seconds=10)
    assert [limiter.allow(1) for _ in range(3)] == [True, True, True]
    assert limiter.allow(1) is False


def test_limiter_counts_users_separately() -> None:
    """Чужой флуд не должен блокировать остальных."""
    limiter = RateLimiter(burst=1, window_seconds=10)
    assert limiter.allow(1) is True
    assert limiter.allow(2) is True
    assert limiter.allow(1) is False


def test_limiter_window_expires(monkeypatch) -> None:
    """Спустя окно лимит снова доступен."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        "bot.middlewares.throttling.time.monotonic", lambda: clock["now"]
    )
    limiter = RateLimiter(burst=1, window_seconds=5)
    assert limiter.allow(1) is True
    assert limiter.allow(1) is False
    clock["now"] += 5.1
    assert limiter.allow(1) is True


def test_limiter_sweeps_idle_users(monkeypatch) -> None:
    """Словарь счётчиков не растёт бесконечно.

    Активных пользователей чистка не трогает (они ещё внутри окна),
    поэтому сбрасываем часы: после паузы их записи считаются старыми.
    """
    clock = {"now": 1000.0}
    monkeypatch.setattr(
        "bot.middlewares.throttling.time.monotonic", lambda: clock["now"]
    )
    limiter = RateLimiter(burst=1, window_seconds=1)
    for user_id in range(200):
        limiter.allow(user_id)
    assert len(limiter._hits) == 200

    clock["now"] += 10
    limiter.allow(999)
    assert len(limiter._hits) <= 2, len(limiter._hits)


def test_limiter_rejects_non_positive_burst() -> None:
    """Нулевой лимит сделал бы бота немым — поднимаем до 1."""
    limiter = RateLimiter(burst=0, window_seconds=5)
    assert limiter.allow(1) is True


async def test_middleware_passes_normal_traffic() -> None:
    """Обычное событие доходит до хендлера."""
    middleware = ThrottlingMiddleware(burst=2, window_seconds=5)
    seen: list[str] = []

    async def handler(event, data):
        seen.append("handled")
        return "ok"

    result = await middleware(handler, message_stub("/start"), {})
    assert result == "ok"
    assert seen == ["handled"]


async def test_middleware_answers_callback_without_handler() -> None:
    """Отказ на кнопку — всплывающая подсказка, а не молчание."""
    middleware = ThrottlingMiddleware(burst=1, window_seconds=5)

    async def handler(event, data):
        return "ok"

    await middleware(handler, callback_stub("nav:catalog"), {})
    rejected = await middleware(handler, callback_stub("nav:catalog"), {})
    assert isinstance(rejected, AnswerCallbackQuery)
    assert "секунд" in rejected.text or "сек" in rejected.text


async def test_middleware_answers_message_without_handler() -> None:
    """Отказ на текст — обычное сообщение в тот же чат."""
    middleware = ThrottlingMiddleware(burst=1, window_seconds=5)

    async def handler(event, data):
        return "ok"

    await middleware(handler, message_stub("/start"), {})
    rejected = await middleware(handler, message_stub("/start"), {})
    assert isinstance(rejected, SendMessage)
    assert rejected.chat_id == 5001


async def test_middleware_skips_events_without_user() -> None:
    """Служебные апдейты не должны расходовать лимит пользователя."""
    middleware = ThrottlingMiddleware(burst=1, window_seconds=5)

    async def handler(event, data):
        return "ok"

    class Anonymous:
        from_user = None

    for _ in range(5):
        assert await middleware(handler, Anonymous(), {}) == "ok"
