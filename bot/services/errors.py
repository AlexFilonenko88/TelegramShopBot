"""Доменные ошибки сервисного слоя.

Handlers перехватывают эти ошибки и превращают их в сообщения для
пользователя; инфраструктурные сбои (таймауты сети) сюда не выносятся —
они остаются в клиентах и логируются.
"""

from __future__ import annotations

DEFAULT_USER_MESSAGE = "Что-то пошло не так. Попробуйте ещё раз."
"""Реплика по умолчанию: внутренние детали пользователю не показываем."""


class ServiceError(Exception):
    """Базовая ошибка бизнес-слоя.

    Args:
        message: Текст для логов.
        user_message: Безопасное для показа пользователю объяснение.
    """

    def __init__(self, message: str, user_message: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.user_message = user_message or DEFAULT_USER_MESSAGE


class UserNotFoundError(ServiceError):
    """Пользователь не найден (например, сессия не инициализирована)."""

    def __init__(self, tg_id: int) -> None:
        super().__init__(
            f"Пользователь {tg_id} не найден в БД",
            "Сначала нажмите /start, чтобы зарегистрироваться.",
        )


class ProductUnavailableError(ServiceError):
    """Товар отсутствует в каталоге или снят с продажи."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            f"Товар недоступен: {slug!r}",
            "Этот товар недоступен. Выберите другой в каталоге.",
        )


class AlreadyPurchasedError(ServiceError):
    """Товар уже куплен — повторная продажа не требуется."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            f"Пользователь уже купил товар {slug!r}",
            "Вы уже покупали этот товар — он в разделе «Мои покупки».",
        )


class OrderNotFoundError(ServiceError):
    """Заказ не найден или недоступен пользователю."""

    def __init__(self, order_id: int) -> None:
        super().__init__(
            f"Заказ {order_id} не найден",
            "Заказ не найден. Оформите покупку заново.",
        )


class OrderStateError(ServiceError):
    """Заказ нельзя перевести в запрошенный статус из текущего."""

    def __init__(self, order_id: int, status: str, wanted: str) -> None:
        super().__init__(
            f"Заказ {order_id}: переход {status} -> {wanted} запрещён",
            "Этот заказ уже нельзя оплатить. Оформите новый.",
        )


class PaymentNotFoundError(ServiceError):
    """Уведомление провайдера о платеже, которого нет в нашей БД.

    Такое возможно при тестовых отправках из личного кабинета YooKassa
    или после очистки БД — для пользователя это не ошибка оформления.
    """

    def __init__(self, provider_payment_id: str) -> None:
        super().__init__(
            f"Платёж {provider_payment_id} не найден в БД",
            "Не нашли этот платёж. Проверьте статус заказа кнопкой "
            "«Проверить оплату».",
        )


class PaymentProviderError(ServiceError):
    """Платёжный провайдер отклонил запрос или ответил некорректно."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(
            f"YooKassa: {message}",
            "Платёжная система временно недоступна. Попробуйте позже.",
        )


class PaymentFailedError(ServiceError):
    """Платёж отменён или провалился на стороне провайдера."""

    def __init__(self, reason: str = "") -> None:
        super().__init__(
            f"Платёж не прошёл: {reason or 'без причины'}",
            "Оплата не завершена. Нажмите «Оплатить», чтобы повторить.",
        )


class PermissionDeniedError(ServiceError):
    """Действие требует прав, которых у пользователя нет."""

    def __init__(self, action: str) -> None:
        super().__init__(
            f"Нет прав на действие: {action}",
            "Это действие доступно только администраторам.",
        )


class NotPurchasedError(ServiceError):
    """Материалы товара хочет получить тот, кто его не покупал.

    Отдельно от :class:`PermissionDeniedError`: формулировка про права
    администратора здесь была бы нечестной по отношению к покупателю.
    """

    def __init__(self, user_id: int, product_id: int) -> None:
        super().__init__(
            f"Пользователь {user_id} не покупал товар {product_id}",
            "Вы ещё не покупали этот товар — доступен каталог.",
        )
