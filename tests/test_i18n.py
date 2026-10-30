"""Тесты локализации: выбор языка и подстановка значений.

Режим языков фиксируется в ``tests/conftest.py``, а переключение режима
даёт фикстура ``language_mode`` — иначе результат зависел бы от
``BOT_LANGUAGE_MODE`` в ``.env`` машины разработчика.
"""

import pytest
from bot.i18n import (
    EN,
    ENGLISH,
    RU,
    RUSSIAN,
    SUPPORTED_LANGUAGES,
    _client_language,
    available_languages,
    resolve_language,
    translate,
)


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("en", "en"),
        ("en-US", "en"),
        ("en_GB", "en"),
        ("ru-RU", "ru"),
        ("RU", "ru"),
        ("pt-BR", None),
        ("", None),
        (None, None),
    ],
)
def test_client_language_takes_locale_prefix(
    locale: str | None, expected: str | None
) -> None:
    """Telegram присылает полную локаль, а словари — двухбуквенные."""
    assert _client_language(locale, SUPPORTED_LANGUAGES) == expected


def test_available_languages_follows_mode(language_mode) -> None:
    """Режим ``all`` открывает английский, фиксированный — только себя."""
    language_mode("all")
    assert available_languages() == (RUSSIAN, ENGLISH)
    language_mode("ru")
    assert available_languages() == (RUSSIAN,)


def test_saved_choice_wins_over_client_locale(language_mode) -> None:
    """Явный выбор в боте важнее языка системы телефона."""
    language_mode("all")
    assert resolve_language("en-US", RUSSIAN) == RUSSIAN
    assert resolve_language("ru-RU", ENGLISH) == ENGLISH


def test_client_locale_used_when_nothing_saved(language_mode) -> None:
    """Без сохранённого выбора берётся язык клиента, если он поддержан."""
    language_mode("all")
    assert resolve_language("en-GB") == ENGLISH


def test_client_locale_ignored_in_single_language_mode(language_mode) -> None:
    """В режиме только русского английская локаль не переключает язык."""
    language_mode("ru")
    assert resolve_language("en-GB") == RUSSIAN


def test_unsupported_locale_falls_back_to_default(language_mode) -> None:
    """Португальский не поддержан — отвечаем на языке из конфига."""
    language_mode("all", default=ENGLISH)
    assert resolve_language("pt-BR") == ENGLISH


def test_unsupported_saved_value_ignored(language_mode) -> None:
    """В БД мог остаться язык, который потом убрали из режима."""
    language_mode("ru")
    assert resolve_language("pt-BR", ENGLISH) == RUSSIAN


def test_translate_substitutes_params() -> None:
    """Плейсхолдеры заполняются без исключений."""
    assert "3" in translate("purchases.header", RUSSIAN, count=3)


def test_translate_keeps_template_on_missing_argument() -> None:
    """Нехватка аргумента не должна ронять ответ бота."""
    assert "{count}" in translate("purchases.header", RUSSIAN)


def test_translate_returns_key_when_unknown() -> None:
    """Неизвестный ключ виден в интерфейсе, а не превращается в пустоту."""
    assert translate("no.such.key", RUSSIAN) == "no.such.key"


def test_english_falls_back_to_russian() -> None:
    """Если английского текста нет, показывается русский, а не ключ."""
    missing = set(RU) - set(EN)
    if not missing:
        pytest.skip("все ключи переведены")
    key = sorted(missing)[0]
    assert translate(key, ENGLISH) == RU[key]


def test_both_catalogs_have_same_placeholders() -> None:
    """Переводы не должны терять плейсхолдеры — иначе упадёт форматирование."""
    import re

    pattern = re.compile(r"\{(\w+)\}")
    for key, ru_text in RU.items():
        en_text = EN.get(key)
        if en_text is None:
            continue
        assert set(pattern.findall(ru_text)) == set(
            pattern.findall(en_text)
        ), key
