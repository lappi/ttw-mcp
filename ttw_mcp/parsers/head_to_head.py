"""Разбор страницы противостояния /players/?id=<A>&with=<B>.

Имена лежат в .compare-title тремя блоками: игрок, «VS», соперник.
Заголовок h1 на этой странице содержит слово «Противостояние», а не ФИО,
поэтому якорем служит именно .compare-title.
"""

from bs4 import BeautifulSoup

from ttw_mcp.errors import ParseError
from ttw_mcp.parsers.common import (
    extract_id,
    parse_date,
    parse_int,
    parse_number,
    parse_score,
    require,
    text_of,
)

PARSER = "parse_head_to_head"


def _side(page, column: int) -> tuple[float, int]:
    selector = f"div.compare-content-column-{column}"
    node = require(page.select_one(selector), selector, PARSER)
    rating = parse_number(text_of(require(node.select_one("div.compare-rating"), f"{selector} .compare-rating", PARSER)))
    rank = parse_int(text_of(require(node.select_one("div.compare-position"), f"{selector} .compare-position", PARSER)))
    return rating, rank


def _block(page, index: int, title: str) -> tuple[dict, dict]:
    """Блок «Победы» или «Партии»: два абсолютных значения и два процента.

    Заголовки не подписаны семантическим классом, только порядком в DOM, а
    оба блока используют одинаковую разметку значений. Переставь сайт блоки
    местами — победы и партии поменялись бы молча, поэтому заголовок
    сверяется явно вместо доверия к индексу.
    """
    blocks = page.select("div.compare-block")
    if len(blocks) <= index:
        raise ParseError(PARSER, f"div.compare-block[{index}]")
    block = blocks[index]
    heading = text_of(
        require(
            block.select_one("div.compare-block-title"),
            f"div.compare-block[{index}] .compare-block-title",
            PARSER,
        )
    )
    if heading != title:
        raise ParseError(
            PARSER,
            f"div.compare-block[{index}] .compare-block-title",
            f"ожидался {title!r}, получен {heading!r}",
        )
    left = block.select("div.compare-block-left")
    right = block.select("div.compare-block-right")
    if len(left) < 2 or len(right) < 2:
        raise ParseError(
            PARSER,
            f"div.compare-block[{index}] .compare-block-left/right",
            "ожидались абсолютное значение и процент",
        )
    absolute = {"player": parse_int(text_of(left[0])), "opponent": parse_int(text_of(right[0]))}
    percent = {"player": parse_int(text_of(left[1])), "opponent": parse_int(text_of(right[1]))}
    return absolute, percent


def parse_head_to_head(html: str, player_id: str, opponent_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = require(soup.select_one("div.compare-title"), "div.compare-title", PARSER)
    names = title.select("div")
    if len(names) < 3:
        raise ParseError(PARSER, "div.compare-title > div", "ожидались игрок, VS, соперник")

    player_rating, player_rank = _side(soup, 1)
    opponent_rating, opponent_rank = _side(soup, 3)
    wins, win_pct = _block(soup, 0, "Победы")
    sets, sets_pct = _block(soup, 1, "Партии")

    player_name = text_of(names[0])
    opponent_name = text_of(names[2])

    matches = []
    for item in soup.select("div.game-item-block"):
        tournament_cell = require(
            item.select_one("div.game-item-tournament"),
            "div.game-item-tournament",
            PARSER,
        )
        link = require(
            tournament_cell.select_one("a"), "div.game-item-tournament a", PARSER
        )
        details = item.select("div.game-item-details > div")
        if len(details) < 3:
            raise ParseError(
                PARSER,
                "div.game-item-details > div",
                "ожидались игрок, счёт и соперник",
            )
        # Сайт ставит слева игрока из id, справа — из with; проверено на
        # 11 очных матчах двух разных пар. Сверяем явно: перевернись порядок
        # однажды, счёт поменялся бы местами молча, а так парсер остановится.
        if text_of(details[0]) != player_name:
            raise ParseError(
                PARSER,
                "div.game-item-details > div:first-child",
                f"слева ожидался {player_name!r}, получено {text_of(details[0])!r}",
            )
        raw_score = text_of(details[1])
        score_for, score_against, _ = parse_score(raw_score)
        matches.append(
            {
                "date": parse_date(text_of(tournament_cell)),
                "tournament_id": extract_id(link["href"]),
                "tournament_title": text_of(link),
                "score_raw": raw_score,
                "player_score": score_for,
                "opponent_score": score_against,
            }
        )

    return {
        "player": {
            "id": player_id,
            "name": player_name,
            "current_rating": player_rating,
            "rank": player_rank,
        },
        "opponent": {
            "id": opponent_id,
            "name": opponent_name,
            "current_rating": opponent_rating,
            "rank": opponent_rank,
        },
        "wins": wins,
        "win_pct": win_pct,
        "sets": sets,
        "sets_pct": sets_pct,
        "matches": matches,
    }
