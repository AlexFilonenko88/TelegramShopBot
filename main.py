"""Точка входа бота.

Собирает компоненты, выстраивает цепочку middleware и запускает
long-polling.

Middleware регистрируются как **outer** на конкретных типах событий
(``message``, ``callback_query``), а не на ``update``. Причина в порядке
работы aiogram: у ``Update`` нет ``from_user``, поэтому троттлинг и
аутентификация на уровне апдейта не увидели бы отправителя. Кроме того,
корневые фильтры роутеров (например, ``IsAdminFilter``) проверяются
*до* inner-middleware, так что профиль пользователя должен быть в
контексте ещё до подбора хендлера — это возможно только в outer-цепи.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.chat_action import ChatActionMiddleware
from bot.handlers import build_routers, set_bot_commands
from bot.middlewares import AuthMiddleware, DbSessionMiddleware, I18nMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.yookassa_client import YooKassaClient
from config import Settings, get_settings
from db.session import dispose_engine, init_engine

logger = logging.getLogger(__name__)


def build_dispatcher(settings: Settings, client: YooKassaClient) -> Dispatcher:
    """Создаёт диспетчер с роутерами и цепочкой middleware.

    Args:
        settings: Настройки приложения.
        client: Клиент YooKassa, общий для всех транзакций.

    Returns:
        Готовый к запуску диспетчер.
    """
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(build_routers())

    # Один лимитер на все типы событий: спам кнопками и спам командами
    # должны считаться вместе, иначе лимит обходится их чередованием.
    throttling = ThrottlingMiddleware()
    db_session = DbSessionMiddleware(
        client, return_url=settings.public_base_url
    )
    auth = AuthMiddleware(is_admin_checker=settings.is_admin.__contains__)
    i18n = I18nMiddleware()
    chat_action = ChatActionMiddleware()

    # Порядок регистрации = порядок снаружи внутрь: первым отклоняется
    # флуд (до открытия соединения с БД), затем транзакция, затем
    # профиль и язык, и только у хендлера включается «печатает…».
    for observer in (
        dispatcher.message,
        dispatcher.callback_query,
    ):
        for middleware in (throttling, db_session, auth, i18n, chat_action):
            observer.outer_middleware.register(middleware)

    return dispatcher


async def main() -> None:
    """Запускает бота до остановки процесса."""
    settings = get_settings()
    client = YooKassaClient(
        settings.yookassa_shop_id, settings.yookassa_secret_key
    )
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(settings, client)

    init_engine(
        settings.async_database_url,
        echo=settings.environment == "development",
    )
    try:
        await set_bot_commands(
            bot,
            language=settings.default_language,
            admin_ids=settings.admin_ids,
        )
        logger.info(
            "Бот запущен: окружение=%s, язык=%s",
            settings.environment,
            settings.default_language,
        )
        await dispatcher.start_polling(bot)
    finally:
        await dispose_engine()
        logger.info("Бот остановлен")


def _configure_logging(level: str) -> None:
    """Настраивает корневой логгер приложения."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


if __name__ == "__main__":
    _configure_logging(get_settings().log_level)
    try:
        asyncio.run(main())
    except KeyboardInterrupt, SystemExit:
        logger.info("Остановка по сигналу")
