"""Сборка роутеров aiogram: порядок регистрации — часть логики.

Роутеры накладываются друг на друга фильтрами, и очередность решает, кто
перехватит событие:

1. ``admin`` — его корневые фильтры проверяют права, поэтому FSM-опросы
   анкеты товара недоступны обычному покупателю.
2. ``catalog`` и ``payment`` — inline-навигация покупателя.
3. ``commands`` — точки входа (``/start``, reply-меню) и подхват всего
   текста, который не распознали предыдущие роутеры.

Обработчики ошибок ставятся на корневой роутер: исключение поднимается
вверх по цепочке и ловится там, где зарегистрирован подходящий
``ExceptionTypeFilter``.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from bot.handlers import admin, catalog, commands, errors, payment
from bot.i18n import RUSSIAN, translate

USER_COMMANDS = ("start", "catalog", "purchases", "help", "language", "cancel")
ADMIN_COMMANDS = ("admin", "products", "add_product", "broadcast")
"""Команды, показываемые Telegram в меню «/».``"""

_root: Router | None = None
"""Собранный корневой роутер: модульные роутеры подключаются один раз."""


def build_routers() -> Router:
    """Возвращает корневой роутер со всеми подключёнными модулями.

    Роутеры модулей — синглтоны: aiogram запрещает подключать один роутер
    к двум родителям. Повторный вызов (например, из тестов) возвращает
    тот же собранный корень, а не падает с ``RuntimeError``.
    """
    global _root
    if _root is not None:
        return _root
    root = Router(name="root")
    root.include_router(admin.router)
    root.include_router(catalog.router)
    root.include_router(payment.router)
    root.include_router(commands.router)
    errors.register_error_handlers(root)
    _root = root
    return root


async def set_bot_commands(
    bot: Bot,
    *,
    language: str = RUSSIAN,
    admin_ids: list[int] | None = None,
) -> None:
    """Загружает меню команд: общее для всех и отдельное для админов.

    Args:
        bot: Клиент бота.
        language: Язык подписей команд.
        admin_ids: Telegram ID администраторов; их команды видят только
            они — иначе покупатель видел бы «➕ Добавить товар» и жался
            туда впустую.
    """
    await bot.set_my_commands(
        _commands(USER_COMMANDS, language),
        scope=BotCommandScopeDefault(),
    )
    for chat_id in admin_ids or []:
        await bot.set_my_commands(
            _commands(USER_COMMANDS + ADMIN_COMMANDS, language),
            scope=BotCommandScopeChat(chat_id=chat_id),
        )


def _commands(names: tuple[str, ...], language: str) -> list[BotCommand]:
    """Строит список команд с локализованными описаниями."""
    return [
        BotCommand(
            command=name,
            description=translate(f"cmd.desc.{name}", language),
        )
        for name in names
    ]
