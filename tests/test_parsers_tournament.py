import re

import pytest

from ttw_mcp.errors import ParseError
from ttw_mcp.parsers.tournament import parse_tournament


@pytest.fixture
def tournament(load_fixture):
    return parse_tournament(load_fixture("tournament.html"), "6ad412a")


def test_metadata(tournament):
    assert tournament["tournament_id"] == "6ad412a"
    assert tournament["title"] == "Санкт Петербург. Турнир Энерджи Арена."
    assert tournament["date"] == "2026-09-13"
    assert tournament["address"] == "Санкт Петербург. Спб Парголово Дорога в Каменку 12"
    assert tournament["organizers"] == "<организатор>"
    assert tournament["participants_count"] == 17
    assert tournament["games_count"] == 82


def test_standings_complete(tournament):
    assert len(tournament["standings"]) == 17
    assert tournament["standings"][0]["place"] == 1
    assert tournament["standings"][0]["name"] == "<игрок H>"
    assert tournament["standings"][0]["rating"] == pytest.approx(201.70)
    assert tournament["standings"][0]["delta"] == pytest.approx(5.03)


def test_last_place_row_fields(tournament):
    last = tournament["standings"][-1]
    assert last["place"] == 17
    assert last["player_id"] == "1c18ed8"
    assert last["name"] == "<игрок A>"
    assert last["city"] == "--, -Санкт-Петербург"
    assert last["games"] == 9
    assert last["wins"] == 0
    assert last["losses"] == 9
    assert last["rating"] == pytest.approx(84.78)
    assert last["delta"] == pytest.approx(-5.22)


def test_series_lists_other_editions_with_ids(tournament):
    series = tournament["series"]
    assert len(series) == 5
    assert [s["id"] for s in series] == [
        "423f3e9",
        "7de1a9d",
        "79a8c89",
        "5f86873",
        "6a98dbd",
    ]
    assert series[0]["date"] == "2026-07-05"
    assert series[0]["participants"] == 18
    assert series[0]["games"] == 63


def test_broken_markup_raises_parse_error():
    with pytest.raises(ParseError):
        parse_tournament("<html><body>нет турнира</body></html>", "6ad412a")


def test_intact_markup_with_zero_standings(load_fixture):
    # Вёрстка цела, строк нет: пустой список, а не ошибка.
    html = load_fixture("tournament.html")
    stripped = re.sub(r"<tr><td class=\"player-place-cell\".*?</tr>", "", html, flags=re.S)
    assert parse_tournament(stripped, "6ad412a")["standings"] == []
