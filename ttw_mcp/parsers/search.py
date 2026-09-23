"""Разбор результатов поиска: страница игроков и ajax-список турниров.

Оба источника режутся сервером — игроки на 500 строках, турниры на 20 —
и пагинации не предлагают, поэтому достижение потолка означает неполный
результат и помечается флагом truncated.
"""

from bs4 import BeautifulSoup

from ttw_mcp.errors import InvalidInput, ParseError
from ttw_mcp.parsers.common import (
    extract_id,
    parse_date,
    parse_int,
    parse_number,
    parse_win_loss,
    require,
    split_hand,
    text_of,
)

PLAYER_SEARCH_CAP = 500
TOURNAMENT_SEARCH_CAP = 20

PARSER = "parse_player_search"

_NO_RESULTS = "Никого не найдено"


def parse_player_search(html: str, limit: int) -> dict:
    if limit < 1:
        raise InvalidInput(f"limit должен быть положительным, получено {limit}")
    soup = BeautifulSoup(html, "html.parser")
    # Якорь: на странице с нулём результатов player-list присутствует с
    # пустым tbody, а при изменившейся вёрстке исчезает. Без него «никого не
    # нашлось» и «сайт переделали» выглядят одинаково.
    listing = require(soup.select_one("div.player-list"), "div.player-list", PARSER)
    rows = [row for row in listing.select("tr") if row.select_one("td.player-name-cell")]

    players = []
    for row in rows[:limit]:
        # В ячейке имени две ссылки на одного игрока: первая оборачивает
        # аватар, вторая несёт ФИО. Простое "a" выбрало бы картинку и вернуло
        # пустое имя, поэтому ссылку с изображением отсекаем.
        link = require(
            row.select_one("td.player-name-cell a:not(:has(img))"),
            "td.player-name-cell a:not(:has(img))",
            PARSER,
        )
        stat = text_of(row.select_one("td.player-stat-cell"))
        wins, losses = parse_win_loss(stat)
        player_name, hand = split_hand(text_of(link))
        players.append(
            {
                "id": extract_id(link["href"]),
                "name": player_name,
                "hand": hand,
                "city": text_of(row.select_one("td.player-city-cell")),
                "tournaments": parse_int(text_of(row.select_one("td.player-tournament-cell"))),
                "games": parse_int(text_of(row.select_one("td.player-games-cell"))),
                "wins": wins,
                "losses": losses,
                "rating_current": parse_number(text_of(row.select_one("td.player-rating-cell"))),
                "delta": parse_number(text_of(row.select_one("td.player-delta-cell"))),
                "date": parse_date(text_of(row.select_one("td.player-date-cell"))),
            }
        )

    return {
        "total_found": len(rows),
        "truncated": len(rows) >= PLAYER_SEARCH_CAP,
        "players": players,
    }


def parse_tournament_search(html: str) -> dict:
    """Разбирает ответ ajax-действия get_tournaments_by_name.

    Принимает ТОЛЬКО этот фрагмент: плоский список вида
    <div><a href="/tournaments/?id=…">название</a></div> и ничего больше.

    Отбор идёт по всем ссылкам документа, поэтому целую страницу сюда
    передавать нельзя — любая ссылка с /tournaments/ в href, хоть из
    навигации, хоть из бокового блока, попала бы в результат как найденный
    турнир. Ограничение держится на вызывающей стороне, а не на коде.

    Пустую выдачу сайт помечает текстом «Никого не найдено.», а на снятое
    ajax-действие отвечает строкой «0». Первое — честный пустой список,
    второе — ParseError: иначе отключённый эндпоинт выглядел бы как
    «таких турниров не существует».
    """
    soup = BeautifulSoup(html, "html.parser")
    tournaments = [
        {"id": extract_id(link["href"]), "title": text_of(link)}
        for link in soup.select("a")
        if "/tournaments/" in link.get("href", "")
    ]
    if not tournaments and html.strip() and _NO_RESULTS not in html:
        raise ParseError(
            "parse_tournament_search",
            'a[href*="/tournaments/"]',
            f"ответ без ссылок и без пометки о пустой выдаче: {html.strip()[:40]!r}",
        )
    return {
        "total_found": len(tournaments),
        "truncated": len(tournaments) >= TOURNAMENT_SEARCH_CAP,
        "tournaments": tournaments,
    }
