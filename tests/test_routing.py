"""Тесты сборки роутеров, фильтров и клавиатур.

Telegram здесь не нужен: проверяется то, что ломается молча — порядок
роутеров, распознавание callback-данных и соответствие кнопок текстам.
"""

import inspect

import pytest
from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from bot.handlers import (
    ADMIN_COMMANDS,
    USER_COMMANDS,
    build_routers,
    set_bot_commands,
)
from bot.i18n import ENGLISH, RUSSIAN, translate
from bot.keyboards.callback_data import (
    AdminCallback,
    NavCallback,
    OrderCallback,
    ProductCallback,
)
from bot.keyboards.reply import main_menu_keyboard, resolve_menu_action

from tests.factories import callback_stub, message_stub


def _walk(router):
    yield router
    for child in router.sub_routers:
        yield from _walk(child)


def test_router_order_is_significant() -> None:
    """Админка должна идти первой: её фильтры отсекают покупателей."""
    root = build_routers()
    assert [r.name for r in root.sub_routers] == [
        "admin",
        "catalog",
        "payment",
        "commands",
    ]


def test_dispatcher_accepts_routers() -> None:
    """Корневой роутер подключается к Dispatcher без конфликтов."""
    dispatcher = Dispatcher()
    dispatcher.include_router(build_routers())
    assert dispatcher.sub_routers


def test_all_handler_injections_are_known() -> None:
    """Опечатка в имени параметра роняет хендлер только в рантайме."""
    known = {
        "session",
        "users",
        "products",
        "orders",
        "payments",
        "purchases",
        "user_service",
        "product_service",
        "payment_service",
        "tg_id",
        "profile",
        "language",
        "state",
        "raw_state",
        "fsm_storage",
        "bot",
        "dispatcher",
        "callback_data",
        "command",
        "event",
        "exception",
    }
    checked = 0
    for router in _walk(build_routers()):
        for event_name, observer in router.observers.items():
            for handler in observer.handlers:
                params = list(
                    inspect.signature(handler.callback).parameters.items()
                )
                for index, (name, param) in enumerate(params):
                    if index == 0 or param.default is not param.empty:
                        continue
                    if param.kind in (param.VAR_KEYWORD, param.VAR_POSITIONAL):
                        continue
                    assert name in known or name == event_name, (
                        f"{handler.callback.__qualname__}: неизвестная "
                        f"инъекция {name!r}"
                    )
                checked += 1
    assert checked > 30, checked


async def test_deep_link_filter_matches_only_product_start() -> None:
    """``/start product:x`` не должен попадать в обычный ``/start``."""
    deep = CommandStart(magic=F.args.startswith("product:"))
    plain = CommandStart()

    hit = await deep(message_stub("/start product:kurs"), bot=message_stub.bot)
    assert hit and "command" in hit
    assert not await deep(message_stub("/start"), bot=message_stub.bot)
    assert await plain(message_stub("/start"), bot=message_stub.bot)


async def test_unknown_command_filter() -> None:
    """Неизвестная команда ловится префиксом «/», а не catch-all."""
    assert F.text.startswith("/").resolve(message_stub("/shop me")) is True
    assert F.text.startswith("/").resolve(message_stub("привет")) is False
    assert F.text.startswith("/").resolve(message_stub(None)) is None


@pytest.mark.parametrize(
    ("data", "model", "expected_action"),
    [
        ("nav:catalog", NavCallback, "catalog"),
        ("prod:open:kurs", ProductCallback, "open"),
        ("order:check_payment:7", OrderCallback, "check_payment"),
        ("adm:stats:", AdminCallback, "stats"),
    ],
)
async def test_callback_factories_parse_own_prefix(
    data: str, model, expected_action: str
) -> None:
    """Каждая кнопка разбирается только своим префиксом."""
    parsed = model.unpack(data)
    assert parsed.action == expected_action
    assert parsed.pack() == data


async def test_callback_filter_rejects_foreign_prefix() -> None:
    """Нажатие чужой кнопки не должно срабатывать в этом хендлере."""
    result = await ProductCallback.filter()(callback_stub("nav:catalog"))
    assert not result


def test_callback_data_fits_telegram_limit() -> None:
    """Telegram ограничивает callback_data 64 байтами."""
    packed = ProductCallback(action="get_file", slug="a" * 40).pack()
    assert len(packed.encode()) <= 64


def test_menu_keyboard_matches_translations() -> None:
    """Подписи кнопок и их разбор не должны расходиться."""
    for language in (RUSSIAN, ENGLISH):
        keyboard = main_menu_keyboard(language)
        labels = [b.text for row in keyboard.keyboard for b in row]
        assert labels
        for label in labels:
            assert resolve_menu_action(label) is not None, label


def test_resolve_menu_action_ignores_plain_text() -> None:
    """Обычный текст не считается нажатием кнопки меню."""
    assert resolve_menu_action("привет") is None
    assert resolve_menu_action(None) is None
    assert resolve_menu_action("   ") is None


def test_resolve_menu_action_is_case_insensitive() -> None:
    """Клиенты могут прислать подпись в другом регистре."""
    label = translate("menu.catalog", RUSSIAN)
    assert resolve_menu_action(label.upper()) == "catalog"


def test_command_descriptions_exist() -> None:
    """У каждой команды из меню есть описание в обоих языках."""
    for name in USER_COMMANDS + ADMIN_COMMANDS:
        for language in (RUSSIAN, ENGLISH):
            text = translate(f"cmd.desc.{name}", language)
            assert text != f"cmd.desc.{name}", (name, language)


async def test_set_bot_commands_registers_admin_scope() -> None:
    """Админские команды видны только админам — через scope чата."""
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.set_my_commands = AsyncMock()
    await set_bot_commands(bot, admin_ids=[111, 222])
    assert bot.set_my_commands.await_count == 3
    scopes = [
        call.kwargs["scope"] for call in bot.set_my_commands.await_args_list
    ]
    assert scopes[0].type == "default"
    assert {scope.chat_id for scope in scopes[1:]} == {111, 222}
