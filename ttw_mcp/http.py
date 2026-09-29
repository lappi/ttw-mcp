"""Запуск сервера по Streamable HTTP — для хостинга в контейнере.

Сервер без состояния: каждый POST /mcp обрабатывается независимо, ответ —
обычный JSON без SSE. Так он переживает перезапуски и параллельные копии
контейнера, которые serverless-платформа поднимает и гасит сама.

Доступ закрыт токеном из переменной окружения TTW_MCP_TOKEN: открытый адрес
был бы прокси к сайту, который просит не обходить себя автоматически. Без
токена процесс не стартует.
"""

import hmac
import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from ttw_mcp.server import mcp


class BearerGate:
    """Пропускает только запросы с Authorization: Bearer <токен>."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, self._expected):
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
    return BearerGate(inner, token)


def main() -> None:
    uvicorn.run(app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
