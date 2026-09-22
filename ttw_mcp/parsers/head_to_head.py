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


def _block(page, index: int) -> tuple[dict, dict]:
    """Блок «Победы» или «Партии»: два абсолютных значения и два процента."""
    blocks = page.select("div.compare-block")
    if len(blocks) <= index:
        raise ParseError(PARSER, f"div.compare-block[{index}]")
    block = blocks[index]
    left = block.select("div.compare-block-left")
    right = block.select("div.compare-block-right")
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
    wins, win_pct = _block(soup, 0)
    sets, sets_pct = _block(soup, 1)

    matches = []
    for item in soup.select("div.game-item-block"):
        tournament_cell = item.select_one("div.game-item-tournament")
        link = tournament_cell.select_one("a")
        details = item.select("div.game-item-details > div")
        score_for, score_against = (int(x) for x in text_of(details[1]).split(":"))
        matches.append(
            {
                "date": parse_date(text_of(tournament_cell)),
                "tournament_id": extract_id(link["href"]),
                "tournament_title": text_of(link),
                "player_score": score_for,
                "opponent_score": score_against,
            }
        )

    return {
        "player": {
            "id": player_id,
            "name": text_of(names[0]),
            "current_rating": player_rating,
            "rank": player_rank,
        },
        "opponent": {
            "id": opponent_id,
            "name": text_of(names[2]),
            "current_rating": opponent_rating,
            "rank": opponent_rank,
        },
        "wins": wins,
        "win_pct": win_pct,
        "sets": sets,
        "sets_pct": sets_pct,
        "matches": matches,
    }
