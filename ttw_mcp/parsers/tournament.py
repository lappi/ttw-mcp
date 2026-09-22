"""Разбор страницы турнира /tournaments/?id=<hash>.

На странице две таблицы с классами tournament-*: первая описывает сам
турнир, вторая перечисляет другие турниры той же серии. Разделяем их по
порядку строк.

Отдельных матчей турнира страница не содержит: они доступны только со
страниц участников.
"""

from bs4 import BeautifulSoup

from ttw_mcp.errors import ParseError
from ttw_mcp.parsers.common import (
    extract_id,
    parse_date,
    parse_int,
    parse_number,
    parse_win_loss,
    require,
    text_of,
)

PARSER = "parse_tournament"


def _meta_row(row) -> dict:
    # Ссылка здесь есть у каждой строки — и у самого турнира, и у всех строк
    # серии: ячейка ради неё и существует. Её отсутствие означает не «турнира
    # нет», а изменившуюся вёрстку, поэтому пустой id не выдумываем.
    link = require(
        row.select_one("td.tournament-info-cell a"),
        "td.tournament-info-cell a",
        PARSER,
    )
    return {
        "id": extract_id(link["href"]),
        "date": parse_date(text_of(row.select_one("td.tournament-date-cell"))),
        "address": text_of(row.select_one("td.tournament-address-cell")),
        "organizers": text_of(row.select_one("td.tournament-organizer-cell")),
        "participants": parse_int(text_of(row.select_one("td.tournament-num-players-cell"))),
        "games": parse_int(text_of(row.select_one("td.tournament-num-games-cell"))),
    }


def parse_tournament(html: str, tournament_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    page = require(soup.select_one("div.tournament-page"), "div.tournament-page", PARSER)
    title_node = require(page.select_one("h1 span"), "div.tournament-page h1 span", PARSER)

    meta_rows = [row for row in page.select("tr") if row.select_one("td.tournament-date-cell")]
    if not meta_rows:
        raise ParseError(PARSER, "td.tournament-date-cell")
    own = _meta_row(meta_rows[0])
    if own["id"] != tournament_id:
        raise ParseError(
            PARSER,
            "td.tournament-info-cell a",
            f"первая строка описывает турнир {own['id']!r}, запрошен {tournament_id!r}",
        )
    series = [_meta_row(row) for row in meta_rows[1:]]

    standings = []
    for row in page.select("tr"):
        place_cell = row.select_one("td.player-place-cell")
        if place_cell is None:
            continue
        link = require(row.select_one("td.player-name-cell a"), "td.player-name-cell a", PARSER)
        stat = text_of(row.select_one("td.player-stat-cell"))
        wins, losses = parse_win_loss(stat)
        standings.append(
            {
                "place": parse_int(text_of(place_cell)),
                "player_id": extract_id(link["href"]),
                "name": text_of(link),
                "city": text_of(row.select_one("td.player-city-cell")),
                "games": parse_int(stat),
                "wins": wins,
                "losses": losses,
                "rating": parse_number(text_of(row.select_one("td.player-rating-cell"))),
                "delta": parse_number(text_of(row.select_one("td.player-delta-cell"))),
            }
        )

    return {
        "tournament_id": tournament_id,
        "title": text_of(title_node),
        "date": own["date"],
        "address": own["address"],
        "organizers": own["organizers"],
        "participants_count": own["participants"],
        "games_count": own["games"],
        "standings": standings,
        "series": series,
    }
