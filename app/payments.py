from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from app.config import Settings

# Production is hosted outside Iran. Zibal explicitly provides .io endpoints
# for foreign servers. Keep the Iranian endpoints as a network fallback so a
# temporary routing or DNS issue on either side does not stop checkout.
ZIBAL_REQUEST_URLS = (
    "https://gateway.zibal.io/v1/request",
    "https://gateway.zibal.ir/v1/request",
)
ZIBAL_VERIFY_URLS = (
    "https://gateway.zibal.io/v1/verify",
    "https://gateway.zibal.ir/v1/verify",
)
ZIBAL_START_URL = "https://gateway.zibal.io/start"


@dataclass(frozen=True)
class ZibalResponse:
    result: int
    payload: dict[str, Any]

    @property
    def message(self) -> str:
        value = self.payload.get("message")
        return str(value) if value else f"Zibal result {self.result}"


class ZibalError(RuntimeError):
    def __init__(self, message: str, *, result: int | None = None) -> None:
        super().__init__(message)
        self.result = result


def _signing_key(settings: Settings) -> bytes:
    # The token is already a deployment secret and never leaves the server.
    # Fall back to the merchant only for isolated tests without a bot token.
    return (settings.bot_token or settings.zibal_merchant).encode("utf-8")


def payment_signature(settings: Settings, mirror_id: int) -> str:
    key = _signing_key(settings)
    if not key:
        return ""
    return hmac.new(key, str(mirror_id).encode("ascii"), hashlib.sha256).hexdigest()


def valid_payment_signature(settings: Settings, mirror_id: int, signature: str) -> bool:
    expected = payment_signature(settings, mirror_id)
    return bool(expected and signature and hmac.compare_digest(expected, signature))


async def _post_json(urls: tuple[str, ...], payload: dict[str, Any]) -> ZibalResponse:
    timeout = ClientTimeout(total=20, connect=8)
    failures: list[str] = []

    async with ClientSession(timeout=timeout) as session:
        for url in urls:
            try:
                async with session.post(url, json=payload) as response:
                    response.raise_for_status()
                    data = await response.json(content_type=None)
            except (ClientError, TimeoutError, ValueError) as exc:
                failures.append(f"{url}: {type(exc).__name__}")
                continue

            if not isinstance(data, dict):
                failures.append(f"{url}: invalid response body")
                continue

            try:
                result = int(data.get("result"))
            except (TypeError, ValueError):
                failures.append(f"{url}: invalid result code")
                continue

            return ZibalResponse(result=result, payload=data)

    details = "; ".join(failures) if failures else "no endpoint responded"
    raise ZibalError(f"ارتباط با درگاه پرداخت برقرار نشد. ({details})")


async def request_zibal_payment(
    settings: Settings,
    *,
    amount_rial: int,
    order_id: str,
    description: str,
) -> int:
    response = await _post_json(
        ZIBAL_REQUEST_URLS,
        {
            "merchant": settings.zibal_merchant,
            "amount": amount_rial,
            "callbackUrl": settings.payment_callback_url,
            "orderId": order_id,
            "description": description,
        },
    )
    if response.result != 100:
        raise ZibalError(response.message, result=response.result)

    try:
        track_id = int(response.payload["trackId"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ZibalError("شناسه پرداخت از زیبال دریافت نشد.", result=response.result) from exc
    return track_id


async def verify_zibal_payment(settings: Settings, track_id: int) -> ZibalResponse:
    return await _post_json(
        ZIBAL_VERIFY_URLS,
        {
            "merchant": settings.zibal_merchant,
            "trackId": track_id,
        },
    )


def zibal_payment_url(track_id: int) -> str:
    return f"{ZIBAL_START_URL}/{track_id}"
