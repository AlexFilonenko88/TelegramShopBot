"""Общие фикстуры тестов.

Настройки читаются из ``.env`` реальной машины и кэшируются ``lru_cache``,
а тестам нужен детерминированный режим локализации: иначе один и тот же
прогон давал бы разные результаты у разработчиков с разным
``BOT_LANGUAGE_MODE``. Подмена — на всю сессию; тестам, где нужен другой
режим, остаётся точечно перекрыть её фикстурой ``language_mode``.
"""

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from bot import i18n

SESSION_SETTINGS = SimpleNamespace(
    bot_language_mode=i18n.RUSSIAN,
    default_language=i18n.RUSSIAN,
)


@pytest.fixture(scope="session", autouse=True)
def fixed_language_mode() -> Iterator[None]:
    """Фиксирует русский режим локализации для всего прогона."""
    original = i18n.get_settings
    i18n.get_settings = lambda: SESSION_SETTINGS  # type: ignore[assignment]
    try:
        yield
    finally:
        i18n.get_settings = original  # type: ignore[assignment]


@pytest.fixture
def language_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    """Возвращает функцию переключения режима ``BOT_LANGUAGE_MODE``.

    Нужна тестам, где проверяется выбор языка пользователем: в
    зафиксированном ``ru`` режиме английский был бы недоступен.
    """

    def switch(mode: str, default: str = i18n.RUSSIAN) -> None:
        monkeypatch.setattr(
            i18n,
            "get_settings",
            lambda: SimpleNamespace(
                bot_language_mode=mode, default_language=default
            ),
        )

    return switch
