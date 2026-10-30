"""Хендлеры команд и reply-меню: точки входа пользователя.

``/start`` (в том числе с deep-link на товар), ``/help``, ``/catalog``,
``/language``, ``/cancel`` и нажатия кнопок главного меню.

Кнопки reply-меню Telegram отдаёт обычным текстом, поэтому нажатие
разбирается по подписям обоих языков
(:func:`bot.keyboards.reply.resolve_menu_action`): язык клиента может не
совпадать с языком, на котором бот уже отвечает.

Deep-link проверяется через ``magic`` самого ``CommandStart``: фильтр
проверяет ``args`` разобранной команды и возвращает их в контекст
хендлера, поэтому отдельный разбор текста в обработчике не нужен.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.catalog import (
    open_product_card,
    render_catalog,
    render_purchases,
)
from bot.handlers.common import safe_edit
from bot.i18n import available_languages, translate
from bot.keyboards.callback_data import NavCallback
from bot.keyboards.inline import language_keyboard
from bot.keyboards.reply import main_menu_keyboard, resolve_menu_action
from bot.services.product_service import ProductService
from bot.services.user_service import UserProfile, UserService

logger = logging.getLogger(__name__)

router = Router(name="commands")

PRODUCT_DEEP_LINK = "product:"
"""Формат ссылки на товар: ``https://t.me/<bot>?start=product:<slug>``."""


@router.message(CommandStart(magic=F.args.startswith(PRODUCT_DEEP_LINK)))
async def handle_start_product(
    message: Message,
    command: CommandObject,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
    state: FSMContext,
) -> None:
    """Открывает карточку товара из deep-link ссылки."""
    await state.clear()
    slug = (command.args or "")[len(PRODUCT_DEEP_LINK) :].strip()
    await open_product_card(
        message,
        slug=slug,
        profile=profile,
        language=language,
        product_service=product_service,
    )


@router.message(CommandStart())
async def handle_start(
    message: Message,
    profile: UserProfile,
    language: str,
    state: FSMContext,
) -> None:
    """``/start``: показать приветствие и главное меню.

    Профиль к этому моменту уже создан ``AuthMiddleware``, поэтому
    команда ничего не пишет в БД — только отвечает текстом.
    """
    await state.clear()
    await message.answer(
        translate("cmd.start", language, name=profile.display_name),
        reply_markup=main_menu_keyboard(language),
    )


@router.message(Command("help"))
async def handle_help(message: Message, language: str) -> None:
    """``/help``: краткая инструкция."""
    await message.answer(
        translate("cmd.help", language),
        reply_markup=main_menu_keyboard(language),
    )


@router.message(Command("catalog"))
async def handle_catalog_command(
    message: Message,
    language: str,
    product_service: ProductService,
    state: FSMContext,
) -> None:
    """``/catalog``: первая страница каталога."""
    await state.clear()
    await render_catalog(message, language, product_service)


@router.message(Command("purchases"))
async def handle_purchases_command(
    message: Message,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
) -> None:
    """``/purchases``: история покупок (тот же код, что и кнопка меню)."""
    await render_purchases(message, profile, language, product_service)


@router.message(Command("language"))
async def handle_language_command(
    message: Message,
    language: str,
    profile: UserProfile,
) -> None:
    """``/language``: выбор языка, если включён режим ``all``."""
    if len(available_languages()) < 2:
        # Один разрешённый язык: показывать переключатель бессмысленно.
        await message.answer(
            translate("cmd.help", language),
            reply_markup=main_menu_keyboard(language),
        )
        return
    await message.answer(
        translate("menu.language", language),
        reply_markup=language_keyboard(profile.language),
    )


@router.callback_query(NavCallback.filter(F.action.startswith("lang_")))
async def handle_language_choice(
    callback: CallbackQuery,
    callback_data: NavCallback,
    language: str,
    user_service: UserService,
) -> None:
    """Сохраняет выбор языка и перерисовывает кнопки с галочкой."""
    code = callback_data.action.removeprefix("lang_")
    if code not in available_languages():
        await callback.answer(
            translate("common.keyboard_dismissed", language),
            show_alert=True,
        )
        return
    await user_service.set_language(callback.from_user.id, code)
    await safe_edit(
        callback.message,
        translate("cmd.start", code, name=callback.from_user.first_name),
        language_keyboard(code),
    )
    await callback.answer()


@router.message(Command("cancel"))
async def handle_cancel(
    message: Message, language: str, state: FSMContext
) -> None:
    """``/cancel`` выходит из любого пошагового диалога."""
    await state.clear()
    await message.answer(
        translate("fsm.cancel", language),
        reply_markup=main_menu_keyboard(language),
    )


@router.message(F.text.startswith("/"))
async def handle_unknown_command(message: Message, language: str) -> None:
    """Команда, которой бот не знает.

    ``Command()`` без списка команд aiogram отвергает, поэтому фильтр
    простой: текст начинается со «/», а все известные команды разбираются
    хендлерами выше.
    """
    await message.answer(
        translate("cmd.unknown", language),
        reply_markup=main_menu_keyboard(language),
    )


@router.message()
async def handle_menu_navigation(
    message: Message,
    profile: UserProfile,
    language: str,
    product_service: ProductService,
    state: FSMContext,
) -> None:
    """Reply-меню и любые текстовые сообщения.

    Регистрация в самом конце важна: тексты админских FSM-опросов
    (название товара, цена, текст рассылки) перехватываются более узкими
    хендлерами с состоянием, а сюда попадает только то, что не распознано.
    """
    action = resolve_menu_action(message.text)
    if action == "catalog":
        await state.clear()
        await render_catalog(message, language, product_service)
        return
    if action == "purchases":
        await render_purchases(message, profile, language, product_service)
        return
    if action == "help":
        await message.answer(
            translate("cmd.help", language),
            reply_markup=main_menu_keyboard(language),
        )
        return
    await message.answer(
        translate("cmd.unknown", language),
        reply_markup=main_menu_keyboard(language),
    )
