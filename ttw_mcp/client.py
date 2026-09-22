"""HTTP-доступ к r.ttw.ru.

Клиент ничего не знает о разметке — он отдаёт текст, а разбирают его
парсеры. Запросы последовательны: сайт работает на PHP 5.6 и отвечает
за 4–17 секунд, параллельные пачки ему вредят.
"""

from types import TracebackType

import httpx

from ttw_mcp.errors import NotFound, UpstreamError


class TtwClient:
    BASE_URL = "https://r.ttw.ru"
    USER_AGENT = "ttw-mcp/0.1 (+https://github.com/cryptolappi/ttw-mcp)"
    TIMEOUT = 30.0
    AJAX_PATH = "/wp-admin/admin-ajax.php"

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": self.USER_AGENT},
            transport=transport,
            follow_redirects=True,
        )

    def get_html(self, path: str, params: dict[str, str]) -> str:
        return self._send("GET", path, params=params)

    def post_ajax(self, action: str, **fields: str) -> str:
        return self._send("POST", self.AJAX_PATH, data={"action": action, **fields})

    def _send(self, method: str, path: str, **kwargs) -> str:
        # Полный адрес с параметрами: в сообщении об ошибке он нужен целиком,
        # иначе непонятно, какой именно запрос не прошёл.
        url = str(self._client.build_request(method, path, **kwargs).url)
        last: Exception | None = None
        for _ in range(2):  # один повтор, только на сетевую ошибку
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                last = exc
                continue
            except httpx.RequestError as exc:
                # Цикл редиректов и битая кодировка лежат РЯДОМ с
                # TransportError, а не под ним, и повтор их не лечит. Но выйти
                # наружу они обязаны как UpstreamError: вызывающий ловит
                # TtwError, и сырое httpx-исключение прошло бы мимо всей
                # типизации ошибок.
                raise UpstreamError(url, f"{type(exc).__name__}: {exc}") from exc
            if response.status_code == 404:
                raise NotFound(f"{response.url} — страница не найдена")
            if response.status_code >= 400:
                raise UpstreamError(str(response.url), f"HTTP {response.status_code}")
            return response.text
        raise UpstreamError(
            url, f"{type(last).__name__}: {last} — две попытки, таймаут {self._timeout} с"
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TtwClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
