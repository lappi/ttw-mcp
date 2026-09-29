"""Запуск сервера по Streamable HTTP — для хостинга в контейнере.

Сервер без состояния: каждый POST /mcp обрабатывается независимо, ответ —
обычный JSON без SSE. Так он переживает перезапуски и параллельные копии
контейнера, которые serverless-платформа поднимает и гасит сама.

Доступ закрыт токеном из переменной окружения TTW_MCP_TOKEN: открытый адрес
был бы прокси к сайту, который просит не обходить себя автоматически. Без
токена процесс не стартует.

Токен принимается в Authorization: Bearer или в X-Api-Key. Второй нужен
Yandex Serverless Containers: их шлюз считает любой Authorization своим
IAM-токеном и отвечает 403, не пропуская запрос в контейнер.
"""

import hmac
import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from ttw_mcp.server import mcp


class TokenGate:
    """Пропускает только запросы с токеном в Authorization или X-Api-Key."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._bearer = f"Bearer {token}".encode()
        self._key = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            bearer = hmac.compare_digest(headers.get(b"authorization", b""), self._bearer)
            key = hmac.compare_digest(headers.get(b"x-api-key", b""), self._key)
            if not (bearer or key):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"www-authenticate", b"Bearer")],
                    }
                )
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self._app(scope, receive, send)


def app() -> ASGIApp:
    token = os.environ.get("TTW_MCP_TOKEN", "")
    if not token:
        raise SystemExit("TTW_MCP_TOKEN не задан")
    inner = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        # Защита от DNS rebinding рассчитана на localhost; за токеном и на
        # чужом домене она только отвергала бы настоящие запросы.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return TokenGate(inner, token)


def main() -> None:
    uvicorn.run(app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
