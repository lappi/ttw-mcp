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
_HAND = re.compile(r"\b(левая|правая)\b(?:\s*/\s*|\s+)?(?:рук\w*)?", re.IGNORECASE)
_EMPTY_GROUP = re.compile(r"\(\s*[/\s]*\)")
_WALKOVER_WIN = frozenset({"W:Тех", "W:L"})
_WALKOVER_LOSS = frozenset({"Тех:W", "L:W"})
_NOT_PLAYED = "0:0"


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
    """Счёт матча и его исход.

    Счёт встречается и в списке матчей профиля, и в очных встречах, поэтому
    разбор общий для всех парсеров.

    Сайт пишет технический результат четырьмя способами, по-разному для
    победившей и проигравшей стороны, и отдельно помечает несыгранный матч
    счётом 0:0. Все формы замерены на выборке в 4621 матч.

    Возвращает (партии за, партии против, исход). Исход может принимать
    следующие значения:
    - "win": числовой счёт N:M, где N > M
    - "loss": числовой счёт N:M, где N <= M
    - "walkover_win": сайт пишет W:Тех или W:L (техническая победа)
    - "walkover_loss": сайт пишет Тех:W или L:W (техническое поражение)
    - "not_played": счёт 0:0 (несыгранный матч)
    - "unparsed": форма, которой в замерах не было, то есть изменившаяся вёрстка

    Для технического результата и несыгранного матча партии равны None,
    а исходная запись сайта сохраняется вызывающим в score_raw.
    """
    if raw == _NOT_PLAYED:
        return None, None, "not_played"
    if raw in _WALKOVER_WIN:
        return None, None, "walkover_win"
    if raw in _WALKOVER_LOSS:
        return None, None, "walkover_loss"
    match = _SCORE.match(raw)
    if match is None:
        return None, None, "unparsed"
    score_for, score_against = int(match.group(1)), int(match.group(2))
    return score_for, score_against, "win" if score_for > score_against else "loss"


def extract_id(href: str) -> str:
    """Достаёт значение параметра id из ссылки сайта."""
    match = _ID.search(href)
    if match is None:
        raise ParseError("extract_id", "?id=", f"получено {href!r}")
    return match.group(1)


def split_hand(name: str) -> tuple[str, str | None]:
    """Отделяет пометку руки от имени игрока.

    Сайт заводит под нерабочую руку отдельный профиль с отдельным
    идентификатором и помечает это прямо в имени — четырнадцатью разными
    способами на выборке в 2835 имён: в скобках и без, с заглавной и строчной,
    в конце имени и приклеенной к фамилии, со словом «рука» и с опечаткой
    «руков». Оставлять пометку внутри имени значит мешать сравнение имён и
    скрывать от потребителя, что игрок выступает нерабочей рукой с
    существенно другим рейтингом.

    Скобка у имени — свободная заметка, и рука лишь один из её элементов:
    встречается «( левая/шипы)», где «шипы» описывают накладку. Поэтому
    вырезается только сама пометка руки, а остаток заметки сохраняется.

    Возвращает (имя без пометки, "левая" | "правая" | None).
    """
    match = _HAND.search(name)
    if match is None:
        return name, None
    rest = name[: match.start()] + name[match.end() :]
    rest = _EMPTY_GROUP.sub(" ", rest)
    rest = re.sub(r"\(\s+", "(", rest)
    return " ".join(rest.split()), match.group(1).lower()


def require(node: T | None, selector: str, parser: str) -> T:
    """Якорь: нет узла — значит вёрстка изменилась, а не данных нет."""
    if node is None:
        raise ParseError(parser, selector)
    return node


def text_of(node: Any) -> str:
    """Очищенный текст узла BeautifulSoup."""
    return clean(node.get_text())
