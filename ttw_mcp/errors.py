"""Типы ошибок ttw-mcp.

Главное требование: потребитель — языковая модель, поэтому сломанный
парсер обязан отличаться от честно пустого результата.
"""


class TtwError(Exception):
    """Общий предок всех ошибок ttw-mcp."""


class InvalidInput(TtwError):
    """Аргумент инструмента не прошёл проверку; запрос не отправлялся."""


class NotFound(TtwError):
    """Сайт ответил, но запрошенной сущности нет."""


class ParseError(TtwError):
    """Разметка не совпала с ожидаемой — вероятно, сайт изменился."""

    def __init__(self, parser: str, selector: str, detail: str = "") -> None:
        self.parser = parser
        self.selector = selector
        self.detail = detail
        message = f"{parser}: не найден селектор {selector!r}"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


class UpstreamError(TtwError):
    """Сетевой сбой или неуспешный HTTP-код от r.ttw.ru."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"запрос к {url} не удался: {reason}")
