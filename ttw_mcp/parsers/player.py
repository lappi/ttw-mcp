"""Разбор страницы игрока /players/?id=<hash>.

Таблица «Все игры» смешивает три вида строк — заголовок недельного
периода, строку турнира и строку матча. Разбор идёт одним проходом с
запоминанием текущего турнира.
"""

import re

from bs4 import BeautifulSoup

from ttw_mcp.errors import NotFound, ParseError
from ttw_mcp.parsers.common import (
    extract_id,
    parse_date,
    parse_int,
    parse_number,
    parse_score,
    parse_win_loss,
    require,
    split_hand,
    text_of,
)

PARSER = "parse_player_profile"
_NAME_RATING = re.compile(r"^(?P<name>.*?)\s*\((?P<rating>[\d.]+)\)$")


def _split_name_rating(text: str) -> tuple[str, float]:
    match = _NAME_RATING.match(text)
    if match is None:
        raise ParseError(PARSER, "ФИО (рейтинг)", f"получено {text!r}")
    return match.group("name"), float(match.group("rating"))


def _parse_summary(page, player_id: str) -> tuple[str, dict]:
    """Сводная строка: город и агрегаты. Отстаёт от matches на один период.

    Заодно единственная проверка, что сайт отдал страницу запрошенного
    игрока: при редиректе или кеше ответ иначе нёс бы чужие матчи под нашим
    player_id, и единственным намёком была бы пустая сводка.
    """
    info = require(page.select_one("div.player-info"), "div.player-info", PARSER)
    row = require(info.select_one("tbody tr"), "div.player-info tbody tr", PARSER)

    actual = text_of(require(row.select_one("td.player-id-cell"), "td.player-id-cell", PARSER))
    if actual != player_id:
        raise ParseError(
            PARSER,
            "td.player-id-cell",
            f"страница принадлежит игроку {actual!r}, запрошен {player_id!r}",
        )

    counts = row.select("td.player-rating-count-cell")
    if len(counts) < 2:
        raise ParseError(PARSER, "td.player-rating-count-cell", "ожидались две ячейки")
    ratings = [parse_number(part) for part in text_of(counts[1]).split(",")]
    stats = text_of(require(row.select_one("td.player-stat-cell"), "td.player-stat-cell", PARSER))
    wins, losses = parse_win_loss(stats)
    city = text_of(require(row.select_one("td.player-city-cell"), "td.player-city-cell", PARSER))
    tournaments = require(
        row.select_one("td.player-tournament-count-cell"), "td.player-tournament-count-cell", PARSER
    )
    return city, {
        "rated_periods": parse_int(text_of(counts[0])),
        "tournaments_played": parse_int(text_of(tournaments)),
        "rating_min": ratings[0],
        "rating_max": ratings[1],
        "rating_avg": ratings[2],
        "games": parse_int(stats),
        "wins": wins,
        "losses": losses,
        "win_pct": parse_int(stats.rsplit(",", 1)[-1]),
    }


def _parse_all_games(page) -> tuple[list, list, list]:
    periods: list[dict] = []
    tournaments: list[dict] = []
    matches: list[dict] = []
    block = require(page.select_one("div.player-all-games"), "div.player-all-games", PARSER)

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
            link = require(
                tournament_cell.select_one("a"), "td.game-tournament-name-cell a", PARSER
            )
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
            link = require(row.select_one("td.game-name-cell a"), "td.game-name-cell a", PARSER)
            name, rating = _split_name_rating(text_of(link))
            opponent_name, opponent_hand = split_hand(name)
            raw_score = text_of(score_cell)
            score_for, score_against, result = parse_score(raw_score)
            matches.append(
                {
                    "date": current.get("date", ""),
                    "tournament_id": current.get("tournament_id", ""),
                    "tournament_title": current.get("title", ""),
                    "score_raw": raw_score,
                    "score_for": score_for,
                    "score_against": score_against,
                    "result": result,
                    "opponent_id": extract_id(link["href"]),
                    "opponent_name": opponent_name,
                    "opponent_hand": opponent_hand,
                    "opponent_rating": rating,
                    "delta": parse_number(text_of(row.select_one("td.game-delta-cell"))),
                }
            )
    return periods, tournaments, matches


def _seed(periods: list[dict], matches: list[dict]) -> tuple[float | None, str | None]:
    """Стартовый рейтинг и дата первого обсчёта.

    Восстанавливается как rating_after самого раннего периода минус его
    дельта. Метод подтверждается округлостью: система сажает новичка на
    целое число, и на выборке в 193 периода `rating_after − delta` целое
    лишь в 2.6% случаев — но у всех проверенных самых ранних периодов оно
    целое.

    Потолок 30 в `rated_periods` на таблицу периодов не распространяется:
    у профилей с 87 и 91 периодом она показана целиком. Поэтому здесь
    потолок не проверяется.

    Возвращает (None, None), если периодов нет вовсе или таблица периодов
    доказуемо неполна — то есть в списке матчей есть матч раньше начала
    самого раннего периода. Матчи без даты в это сравнение не участвуют:
    `if m.get("date")` отсекает их до сравнения, а не приравнивает пустую
    дату к самой ранней. Выдумывать стартовый рейтинг по не-первому
    периоду нельзя: он будет правдоподобным и неверным.
    """
    if not periods:
        return None, None
    earliest = periods[-1]
    if any(m["date"] < earliest["start"] for m in matches if m.get("date")):
        return None, None
    return round(earliest["rating_after"] - earliest["delta"], 2), earliest["start"]


def _parse_best_wins(page) -> list[dict]:
    """Блок «Лучшие победы» использует другие классы и не даёт id соперника.

    Рейтинг соперника в строке сайт пишет на момент той встречи, а
    собственный рейтинг игрока — сегодняшний, округлённый до целого (и
    постоянный для всех записей блока). Это разные временные основания,
    поэтому поле называется player_rating_current, а не player_rating:
    имя обязано честно говорить, что оно не совпадает по смыслу с
    player_rating_at_match, которым annotate_matches дополнит эти же
    записи.
    """
    block = page.select_one("div.player-best-games")
    if block is None:
        return []
    best: list[dict] = []
    current: dict = {}
    for row in block.select("tr"):
        tournament_cell = row.select_one("td.player-game-tournament-cell")
        if tournament_cell is not None:
            link = require(
                tournament_cell.select_one("a"), "td.player-game-tournament-cell a", PARSER
            )
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
            opponent_name_rated, opponent_rating = _split_name_rating(text_of(names[1]))
            opponent_name, opponent_hand = split_hand(opponent_name_rated)
            raw_score = text_of(score_cell)
            score_for, score_against, _ = parse_score(raw_score)
            best.append(
                {
                    **current,
                    "player_rating_current": own_rating,
                    "score_raw": raw_score,
                    "score_for": score_for,
                    "score_against": score_against,
                    "opponent_name": opponent_name,
                    "opponent_hand": opponent_hand,
                    "opponent_rating": opponent_rating,
                    "delta": parse_number(text_of(row.select_one("td.player-game-delta-cell"))),
                }
            )
    return best


def parse_player_profile(
    html: str,
    player_id: str,
    *,
    include_matches: bool = True,
    matches_since: str | None = None,
) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    page = require(soup.select_one("div.player-page"), "div.player-page", PARSER)
    name_node = require(page.select_one("h1 span"), "div.player-page h1 span", PARSER)

    raw_name = text_of(name_node)
    if not raw_name:
        raise NotFound(f"игрок {player_id} не найден на r.ttw.ru")
    name, hand = split_hand(raw_name)

    rating_node = page.select_one("div.player-all-games th.rating-rating-cell")
    if rating_node is None:
        rating_node = require(
            page.select_one("div.header-rating"), "div.header-rating", PARSER
        )
    rank_node = require(page.select_one("div.header-position"), "div.header-position", PARSER)

    periods, tournaments, matches = _parse_all_games(page)
    city, summary = _parse_summary(page, player_id)
    # _seed обязан получить полный, неотфильтрованный список: его защитная
    # ветка сравнивает даты матчей с началом самого раннего периода и на
    # урезанном списке молча перестанет срабатывать.
    summary["seed_rating"], summary["first_rated_date"] = _seed(periods, matches)
    best_wins = _parse_best_wins(page)

    result = {
        "player_id": player_id,
        "name": name,
        "hand": hand,
        "city": city,
        "rating_current": parse_number(text_of(rating_node)),
        "rank": parse_int(text_of(rank_node)),
        "summary": summary,
        "periods": periods,
        "tournaments": tournaments,
    }
    result["matches_total"] = len(matches)
    result["best_wins_total"] = len(best_wins)
    if include_matches:
        if matches_since is not None:
            matches = [m for m in matches if m["date"] >= matches_since]
        result["matches"] = matches
        result["best_wins"] = best_wins
    return result
