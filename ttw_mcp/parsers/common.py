"""Хелперы, общие для всех парсеров r.ttw.ru.

Все функции чистые: принимают строку, возвращают значение, в сеть не ходят.

Неразрывный пробел записывается экранированно, как "\\xa0": литеральный
U+00A0 в исходнике невидим и теряется при копировании.
"""

import re
from typing import Any, TypeVar

from ttw_mcp.errors import ParseError

T = TypeVar("T")

_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")
_WIN_LOSS = re.compile(r"(\d+)\s*-\s*(\d+)")
_SCORE = re.compile(r"^(\d+):(\d+)$")
_ID = re.compile(r"[?&]id=([0-9a-f]+)")


def clean(text: str) -> str:
    """Схлопывает пробелы и неразрывные пробелы, обрезает края."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def parse_date(text: str) -> str:
    """DD.MM.YYYY -> YYYY-MM-DD."""
    match = _DATE.search(text)
    if match is None:
        raise ParseError("parse_date", "DD.MM.YYYY", f"получено {text!r}")
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def parse_number(text: str) -> float:
    """Первое число в строке, со знаком: '+1.41' -> 1.41."""
    match = _NUMBER.search(text.replace(",", "."))
    if match is None:
        raise ParseError("parse_number", "число", f"получено {text!r}")
    return float(match.group())


def parse_int(text: str) -> int:
    """Первое целое в строке; проценты и пробелы отбрасываются."""
    return int(parse_number(text))


def parse_win_loss(text: str) -> tuple[int, int]:
    """'71-27' -> (71, 27)."""
    match = _WIN_LOSS.search(text)
    if match is None:
        raise ParseError("parse_win_loss", "В-П", f"получено {text!r}")
    return int(match.group(1)), int(match.group(2))


def parse_score(raw: str) -> tuple[int | None, int | None, str]:
    """Счёт матча. Техническую победу сайт пишет как "W:Тех", без партий.

    Возвращает (партии за, партии против, исход). Для обычного счёта исход
    "win" или "loss"; для технической победы — (None, None, "walkover").

    Молча выбросить такой матч нельзя: он сыгран, у него есть соперник и
    рейтинговая дельта, а модель, считающая игры по списку, недосчиталась бы
    одной и не смогла бы об этом узнать. Встречается и в списке матчей
    профиля, и в очных встречах, поэтому живёт здесь, а не в одном парсере.
    """
    match = _SCORE.match(raw)
    if match is None:
        return None, None, "walkover"
    score_for, score_against = int(match.group(1)), int(match.group(2))
    return score_for, score_against, "win" if score_for > score_against else "loss"


def extract_id(href: str) -> str:
    """Достаёт значение параметра id из ссылки сайта."""
    match = _ID.search(href)
    if match is None:
        raise ParseError("extract_id", "?id=", f"получено {href!r}")
    return match.group(1)


def require(node: T | None, selector: str, parser: str) -> T:
    """Якорь: нет узла — значит вёрстка изменилась, а не данных нет."""
    if node is None:
        raise ParseError(parser, selector)
    return node


def text_of(node: Any) -> str:
    """Очищенный текст узла BeautifulSoup."""
    return clean(node.get_text())
