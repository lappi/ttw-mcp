"""Разбор страницы игрока /players/?id=<hash>.

Таблица «Все игры» смешивает три вида строк — заголовок недельного
периода, строку турнира и строку матча. Разбор идёт одним проходом с
запоминанием текущего турнира.
"""

import re

from bs4 import BeautifulSoup

from ttw_mcp.errors import NotFound
from ttw_mcp.parsers.common import (
    extract_id,
    parse_date,
    parse_int,
    parse_number,
    parse_win_loss,
    require,
    text_of,
)

PARSER = "parse_player_profile"
_NAME_RATING = re.compile(r"^(?P<name>.*?)\s*\((?P<rating>[\d.]+)\)$")


def _split_name_rating(text: str) -> tuple[str, float]:
    match = _NAME_RATING.match(text)
    if match is None:
        return text, 0.0
    return match.group("name"), float(match.group("rating"))


def _parse_summary(page, player_id: str) -> tuple[str, dict]:
    """Сводная строка: город и агрегаты. Отстаёт от matches на один период."""
    for row in page.select("tr"):
        cells = row.select("td")
        if len(cells) == 6 and text_of(cells[0]) == player_id:
            ratings = [parse_number(part) for part in text_of(cells[4]).split(",")]
            stats = text_of(cells[5])
            wins, losses = parse_win_loss(stats)
            summary = {
                "rated_periods": parse_int(text_of(cells[2])),
                "tournaments_played": parse_int(text_of(cells[3])),
                "rating_min": ratings[0],
                "rating_max": ratings[1],
                "rating_avg": ratings[2],
                "games": parse_int(stats),
                "wins": wins,
                "losses": losses,
                "win_pct": parse_int(stats.rsplit(",", 1)[-1]),
            }
            return text_of(cells[1]), summary
    return "", {}


def _parse_all_games(page) -> tuple[list, list, list]:
    periods: list[dict] = []
    tournaments: list[dict] = []
    matches: list[dict] = []
    block = page.select_one("div.player-all-games")
    if block is None:
        return periods, tournaments, matches

    current: dict = {}
    for row in block.select("tr"):
        title_cell = row.select_one("th.rating-title-cell")
        if title_cell is not None:
            start, end = text_of(title_cell).split("-")
            periods.append(
                {
                    "start": parse_date(start),
                    "end": parse_date(end),
                    "rating_after": parse_number(text_of(row.select_one("th.rating-rating-cell"))),
                    "delta": parse_number(text_of(row.select_one("th.rating-delta-cell"))),
                }
            )
            continue

        tournament_cell = row.select_one("td.game-tournament-name-cell")
        if tournament_cell is not None:
            link = tournament_cell.select_one("a")
            current = {
                "date": parse_date(text_of(tournament_cell)),
                "tournament_id": extract_id(link["href"]),
                "title": text_of(link),
                "delta": parse_number(text_of(row.select_one("td.game-tournament-delta-cell"))),
            }
            tournaments.append(current)
            continue

        score_cell = row.select_one("td.game-score-cell")
        if score_cell is not None:
            score_parts = text_of(score_cell).split(":")
            if len(score_parts) != 2 or not all(p.strip().isdigit() for p in score_parts):
                # Технический результат ("W:Тех" — победа техническим
                # поражением соперника) не выражается числовым счётом.
                continue
            link = row.select_one("td.game-name-cell a")
            name, rating = _split_name_rating(text_of(link))
            score_for, score_against = (int(x) for x in score_parts)
            matches.append(
                {
                    "date": current.get("date", ""),
                    "tournament_id": current.get("tournament_id", ""),
                    "tournament_title": current.get("title", ""),
                    "score_for": score_for,
                    "score_against": score_against,
                    "result": "win" if score_for > score_against else "loss",
                    "opponent_id": extract_id(link["href"]),
                    "opponent_name": name,
                    "opponent_rating": rating,
                    "delta": parse_number(text_of(row.select_one("td.game-delta-cell"))),
                }
            )
    return periods, tournaments, matches


def _parse_best_wins(page) -> list[dict]:
    """Блок «Лучшие победы» использует другие классы и не даёт id соперника."""
    block = page.select_one("div.player-best-games")
    if block is None:
        return []
    best: list[dict] = []
    current: dict = {}
    for row in block.select("tr"):
        tournament_cell = row.select_one("td.player-game-tournament-cell")
        if tournament_cell is not None:
            link = tournament_cell.select_one("a")
            current = {
                "date": parse_date(text_of(tournament_cell)),
                "tournament_id": extract_id(link["href"]),
                "tournament_title": text_of(link),
            }
            continue
        score_cell = row.select_one("td.player-game-score-cell")
        if score_cell is not None:
            names = row.select("td.player-name-cell")
            _, own_rating = _split_name_rating(text_of(names[0]))
            opponent_name, opponent_rating = _split_name_rating(text_of(names[1]))
            score_for, score_against = (int(x) for x in text_of(score_cell).split(":"))
            best.append(
                {
                    **current,
                    "player_rating": own_rating,
                    "score_for": score_for,
                    "score_against": score_against,
                    "opponent_name": opponent_name,
                    "opponent_rating": opponent_rating,
                    "delta": parse_number(text_of(row.select_one("td.player-game-delta-cell"))),
                }
            )
    return best


def parse_player_profile(html: str, player_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    page = require(soup.select_one("div.player-page"), "div.player-page", PARSER)
    name_node = require(page.select_one("h1 span"), "div.player-page h1 span", PARSER)

    name = text_of(name_node)
    if not name:
        raise NotFound(f"игрок {player_id} не найден на r.ttw.ru")

    rating_node = page.select_one("div.player-all-games th.rating-rating-cell")
    if rating_node is None:
        rating_node = require(
            page.select_one("div.header-rating"), "div.header-rating", PARSER
        )
    rank_node = require(page.select_one("div.header-position"), "div.header-position", PARSER)

    periods, tournaments, matches = _parse_all_games(page)
    city, summary = _parse_summary(page, player_id)
    return {
        "player_id": player_id,
        "name": name,
        "city": city,
        "current_rating": parse_number(text_of(rating_node)),
        "rank": parse_int(text_of(rank_node)),
        "summary": summary,
        "periods": periods,
        "tournaments": tournaments,
        "matches": matches,
        "best_wins": _parse_best_wins(page),
    }
