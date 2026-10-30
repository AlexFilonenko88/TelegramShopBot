"""Тесты клиента YooKassa без сети.

HTTP-сессия подменяется заглушкой: проверяются маппинг статусов,
повторы на 5xx и отказ повторять 4xx — то, что нельзя проверить руками.
"""

import json
from typing import Any

import pytest
from bot.services.errors import PaymentProviderError
from bot.services.yookassa_client import (
    UnknownPaymentStatusError,
    YooKassaClient,
    map_provider_status,
)
from db.models.enums import PaymentStatus


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pending", PaymentStatus.PENDING),
        ("waiting_for_capture", PaymentStatus.PROCESSING),
        ("succeeded", PaymentStatus.SUCCEEDED),
        ("canceled", PaymentStatus.CANCELED),
    ],
)
def test_map_provider_status_known(raw: str, expected: PaymentStatus) -> None:
    """Все статусы YooKassa, которые бот умеет обрабатывать."""
    assert map_provider_status(raw) is expected


def test_map_provider_status_unknown_raises() -> None:
    """Незнакомый статус не маппится в pending: это выдало бы товар даром."""
    with pytest.raises(UnknownPaymentStatusError) as exc:
        map_provider_status("refund_pending")
    assert exc.value.raw_status == "refund_pending"


class FakeResponse:
    """Минимальный ответ aiohttp: статус и тело."""

    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._payload = payload

    async def text(self) -> str:
        return json.dumps(self._payload)


class FakeRequestContext:
    """Асинхронный контекстный менеджер вместо ``session.request``."""

    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeResponse:
        return self._response

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeSession:
    """Сессия, отдающая заранее заданные ответы по очереди."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def request(self, *args: Any, **kwargs: Any) -> FakeRequestContext:
        self.calls += 1
        return FakeRequestContext(self._responses.pop(0))


def build_client(session: FakeSession) -> YooKassaClient:
    """Клиент с заглушкой вместо сети и без пауз между повторами."""
    client = YooKassaClient("shop", "secret", session=session)  # type: ignore[arg-type]
    return client


async def test_create_payment_returns_intent() -> None:
    """Успешный ответ разбирается в PaymentIntent со ссылкой."""
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "id": "pay-1",
                    "status": "pending",
                    "confirmation": {
                        "confirmation_url": "https://pay/1",
                    },
                },
            )
        ]
    )
    intent = await build_client(session).create_payment(
        idempotency_key="order-1",
        amount_kopecks=199000,
        currency="RUB",
        description="Курс",
        return_url="https://bot/return",
        metadata={"order_id": 1},
    )
    assert intent.provider_payment_id == "pay-1"
    assert intent.status is PaymentStatus.PENDING
    assert intent.confirmation_url == "https://pay/1"
    assert session.calls == 1


async def test_retry_on_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """503 повторяется: провайдер отвечает так при перегрузке."""
    monkeypatch.setattr("bot.services.yookassa_client.RETRY_BACKOFF_SECONDS", 0)
    session = FakeSession(
        [
            FakeResponse(503, {"type": "error"}),
            FakeResponse(
                200, {"id": "pay-2", "status": "pending", "confirmation": {}}
            ),
        ]
    )
    intent = await build_client(session).get_payment("pay-2")
    assert intent.provider_payment_id == "pay-2"
    assert session.calls == 2


async def test_no_retry_on_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """400 повторять бессмысленно: запрос не станет валидным."""
    monkeypatch.setattr("bot.services.yookassa_client.RETRY_BACKOFF_SECONDS", 0)
    session = FakeSession([FakeResponse(400, {"type": "error"})])
    with pytest.raises(PaymentProviderError) as exc:
        await build_client(session).get_payment("pay-3")
    assert exc.value.status_code == 400
    assert session.calls == 1


async def test_gives_up_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """После исчерпания попыток — доменная ошибка, а не «висим»."""
    monkeypatch.setattr("bot.services.yookassa_client.RETRY_BACKOFF_SECONDS", 0)
    session = FakeSession([FakeResponse(500, {}) for _ in range(3)])
    with pytest.raises(PaymentProviderError):
        await build_client(session).get_payment("pay-4")
    assert session.calls == 3


async def test_non_json_response_is_provider_error() -> None:
    """HTML от прокси не должен ломать разбор JSON-исключением."""

    class BrokenResponse(FakeResponse):
        async def text(self) -> str:
            return "<html>502 Bad Gateway</html>"

    session = FakeSession([BrokenResponse(200, {})])
    with pytest.raises(PaymentProviderError):
        await build_client(session).get_payment("pay-5")


async def test_missing_id_is_provider_error() -> None:
    """Ответ без id считается некорректным, а не «пустым платежом»."""
    session = FakeSession([FakeResponse(200, {"status": "pending"})])
    with pytest.raises(PaymentProviderError):
        await build_client(session).get_payment("pay-6")
