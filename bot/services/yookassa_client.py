"""Клиент YooKassa API v3.

Слой целиком отвечает за HTTP: форматирование запроса, разбор ответа,
повторы при сетевых сбоях. Бизнес-решения (создавать ли новый счёт,
выдавать ли товар) здесь отсутствуют — они в :class:`PaymentService`.

Документация: https://yookassa.ru/developers/api (создание платежа —
``POST /v3/payments``, получение — ``GET /v3/payments/{id}``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aiohttp
from db.models.enums import PaymentStatus

from bot.services.errors import PaymentProviderError
from bot.services.money import kopecks_to_str

logger = logging.getLogger(__name__)

YOOKASSA_API_URL = "https://api.yookassa.ru/v3"
DEFAULT_TIMEOUT_SECONDS = 15
MAX_RETRY_COUNT = 3
RETRY_BACKOFF_SECONDS = 1.5
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
"""Коды ответа, при которых запрос безопасно повторить."""

_STATUS_MAP: dict[str, PaymentStatus] = {
    "pending": PaymentStatus.PENDING,
    "waiting_for_capture": PaymentStatus.PROCESSING,
    "processing": PaymentStatus.PROCESSING,
    "succeeded": PaymentStatus.SUCCEEDED,
    "canceled": PaymentStatus.CANCELED,
}


class UnknownPaymentStatusError(PaymentProviderError):
    """Провайдер вернул статус, которого нет в нашей модели."""

    def __init__(self, raw_status: str) -> None:
        self.raw_status = raw_status
        super().__init__(f"неизвестный статус платежа {raw_status!r}")


@dataclass(frozen=True)
class PaymentIntent:
    """Результат создания счёта в YooKassa.

    Attributes:
        provider_payment_id: Идентификатор платежа на стороне провайдера.
        status: Переведённый статус платежа.
        confirmation_url: Ссылка, по которой пользователь платит.
        raw_response: Исходный JSON для записи в ``payments.raw_response``.
    """

    provider_payment_id: str
    status: PaymentStatus
    confirmation_url: str | None
    raw_response: dict[str, Any]


def map_provider_status(raw_status: str) -> PaymentStatus:
    """Переводит статус YooKassa в статус проекта.

    Args:
        raw_status: Значение поля ``status`` из ответа провайдера.

    Returns:
        Соответствующий член :class:`PaymentStatus`.

    Raises:
        UnknownPaymentStatusError: Если статус незнаком (у YooKassa
            статусы расширяются — молча маппить на «pending» опасно,
            можно выдать неоплаченный товар).
    """
    try:
        return _STATUS_MAP[raw_status]
    except KeyError as exc:
        raise UnknownPaymentStatusError(raw_status) from exc


class YooKassaClient:
    """Асинхронный клиент HTTP API YooKassa."""

    def __init__(
        self,
        shop_id: str,
        secret_key: str,
        *,
        base_url: str = YOOKASSA_API_URL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Args:
        shop_id: Идентификатор магазина (``YOOKASSA_SHOP_ID``).
        secret_key: Секретный ключ (``YOOKASSA_SECRET_KEY``).
        base_url: База API; переопределяется в тестах.
        timeout_seconds: Таймаут одного HTTP-запроса.
        session: Готовая сессия (для переиспользования пула);
            если не передана — создаётся на каждый вызов.
        """
        self._shop_id = shop_id
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._external_session = session

    async def create_payment(
        self,
        *,
        idempotency_key: str,
        amount_kopecks: int,
        currency: str,
        description: str,
        return_url: str,
        metadata: dict[str, Any],
    ) -> PaymentIntent:
        """Создаёт счёт на оплату.

        Args:
            idempotency_key: Ключ идемпотентности (наш ``payment.id``),
                чтобы повтор после таймаута не создал второй счёт.
            amount_kopecks: Сумма в копейках.
            currency: Код валюты (``RUB``).
            description: Что покупает пользователь (видно в чеке).
            return_url: Куда YooKassa вернёт пользователя после оплаты.
            metadata: Произвольные поля, вернутся в webhook-уведомлении.

        Returns:
            :class:`PaymentIntent` со ссылкой на оплату.

        Raises:
            PaymentProviderError: На 4xx или после исчерпания повторов.
        """
        payload = {
            "amount": {
                "value": kopecks_to_str(amount_kopecks),
                "currency": currency,
            },
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": metadata,
        }
        data = await self._request(
            "POST",
            "/payments",
            json_payload=payload,
            idempotency_key=idempotency_key,
        )
        return self._parse_intent(data)

    async def get_payment(self, provider_payment_id: str) -> PaymentIntent:
        """Запрашивает актуальное состояние платежа.

        Используется кнопкой «Проверить оплату», чтобы не зависеть от
        доставки webhook.
        """
        data = await self._request("GET", f"/payments/{provider_payment_id}")
        return self._parse_intent(data)

    @staticmethod
    def _parse_intent(data: dict[str, Any]) -> PaymentIntent:
        """Собирает :class:`PaymentIntent` из ответа API.

        Raises:
            PaymentProviderError: Если в ответе нет обязательных полей.
        """
        provider_id = data.get("id")
        raw_status = data.get("status")
        if not isinstance(provider_id, str) or not isinstance(raw_status, str):
            raise PaymentProviderError(
                f"некорректный ответ API: {sorted(data)!r}"
            )
        confirmation = data.get("confirmation") or {}
        url = confirmation.get("confirmation_url")
        return PaymentIntent(
            provider_payment_id=provider_id,
            status=map_provider_status(raw_status),
            confirmation_url=url if isinstance(url, str) else None,
            raw_response=data,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Выполняет HTTP-запрос с повторами.

        Повторяются только сетевые сбои и 429/5xx: на 4xx повтор
        бессмысленен. Идемпотентность гарантирует, что повтор POST не
        создаст дубль счёта.

        Args:
            method: HTTP-метод.
            path: Путь относительно базы API.
            json_payload: Тело запроса.
            idempotency_key: Заголовок ``Idempotence-Key``.

        Returns:
            Разобранный JSON-ответ.

        Raises:
            PaymentProviderError: При ошибке провайдера или после
                исчерпания попыток.
        """
        headers = (
            {"Idempotence-Key": idempotency_key} if idempotency_key else {}
        )
        url = f"{self._base_url}{path}"
        last_error = ""
        for attempt in range(1, MAX_RETRY_COUNT + 1):
            try:
                status, text = await self._once(
                    method, url, headers, json_payload
                )
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "YooKassa %s %s сбой сети (%s), попытка %d/%d",
                    method,
                    path,
                    type(exc).__name__,
                    attempt,
                    MAX_RETRY_COUNT,
                )
                await self._sleep_before_retry(attempt)
                continue
            if status in RETRYABLE_STATUSES:
                last_error = f"HTTP {status}"
                logger.warning(
                    "YooKassa %s %s -> HTTP %s (попытка %d/%d)",
                    method,
                    path,
                    status,
                    attempt,
                    MAX_RETRY_COUNT,
                )
                await self._sleep_before_retry(attempt)
                continue
            if status >= 400:
                raise PaymentProviderError(
                    f"{method} {path} -> HTTP {status}: {text[:300]}",
                    status_code=status,
                )
            return await self._parse_json(text)
        raise PaymentProviderError(
            f"нет ответа от платёжной системы после {MAX_RETRY_COUNT} "
            f"попыток ({last_error})"
        )

    async def _once(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_payload: dict[str, Any] | None,
    ) -> tuple[int, str]:
        """Один HTTP-запрос: статус и текст ответа без разбора.

        Авторизация передаётся готовым заголовком: ``aiohttp.BasicAuth``
        объявлен устаревшим в aiohttp 3.14 и исчезнет в 4.0.
        """
        auth_header = aiohttp.encode_basic_auth(self._shop_id, self._secret_key)
        async with (
            self._session() as session,
            session.request(
                method,
                url,
                json=json_payload,
                headers={**headers, "Authorization": auth_header},
            ) as response,
        ):
            return response.status, await response.text()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[aiohttp.ClientSession]:
        """Даёт сессию: одолженную (не закрывая) или временную."""
        if self._external_session is not None:
            yield self._external_session
            return
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            yield session

    @staticmethod
    async def _sleep_before_retry(attempt: int) -> None:
        """Пауза с линейным backoff перед следующим повтором."""
        if attempt < MAX_RETRY_COUNT:
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

    @staticmethod
    async def _parse_json(text: str) -> dict[str, Any]:
        """Разбирает ответ, сообщая о не-JSON как об ошибке провайдера."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PaymentProviderError(
                f"ответ не является JSON: {text[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise PaymentProviderError(
                f"неожиданная форма ответа: {text[:200]!r}"
            )
        return data
