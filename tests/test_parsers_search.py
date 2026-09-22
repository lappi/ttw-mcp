import pytest

from ttw_mcp.errors import InvalidInput, ParseError
from ttw_mcp.parsers.search import (
    PLAYER_SEARCH_CAP,
    TOURNAMENT_SEARCH_CAP,
    parse_player_search,
    parse_tournament_search,
)


def test_player_search_returns_all_matching_rows(load_fixture):
    result = parse_player_search(load_fixture("search_players_many.html"), limit=200)
    assert result["total_found"] == 177
    assert result["truncated"] is False
    assert len(result["players"]) == 177
    assert [p["id"] for p in result["players"][:2]] == ["104aa33", "436993b"]


def test_player_search_row_fields(load_fixture):
    result = parse_player_search(load_fixture("search_players_many.html"), limit=25)
    player = result["players"][1]
    assert player["id"] == "436993b"
    assert player["name"]
    assert player["city"] == "Башкортостан, Уфа"
    assert player["tournaments"] == 13
    assert player["games"] == 93
    assert player["wins"] == 81
    assert player["losses"] == 12
    assert player["rating"] == pytest.approx(865.0)
    assert player["delta"] == pytest.approx(0.0)
    assert player["date"] == "2026-06-01"


def test_limit_trims_returned_rows_but_not_total(load_fixture):
    result = parse_player_search(load_fixture("search_players_many.html"), limit=1)
    assert result["total_found"] == 177
    assert len(result["players"]) == 1


def test_capped_search_is_flagged_as_truncated(load_fixture):
    result = parse_player_search(load_fixture("search_players_capped.html"), limit=5)
    assert result["total_found"] == PLAYER_SEARCH_CAP
    assert result["truncated"] is True
    assert len(result["players"]) == 5


def test_zero_results_is_empty_list_not_error(load_fixture):
    result = parse_player_search(load_fixture("search_players_zero.html"), limit=25)
    assert result == {"total_found": 0, "truncated": False, "players": []}


def test_broken_markup_raises_parse_error():
    with pytest.raises(ParseError):
        parse_player_search("<html><body>ничего похожего</body></html>", limit=25)


def test_renamed_class_raises_instead_of_reporting_zero(load_fixture):
    # Ровно тот случай, который прежде был неотличим от «никого не нашлось».
    broken = load_fixture("search_players_many.html").replace("player-list", "playerList")
    with pytest.raises(ParseError):
        parse_player_search(broken, limit=25)


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_limit_is_rejected(load_fixture, bad):
    with pytest.raises(InvalidInput):
        parse_player_search(load_fixture("search_players_many.html"), limit=bad)


def test_hand_marker_is_split_out_of_the_name(load_fixture):
    # Поправка 5: в этой выдаче ровно один игрок с пометкой руки, «левая».
    result = parse_player_search(load_fixture("search_players_many.html"), limit=200)
    with_hand = [p for p in result["players"] if p["hand"]]
    assert len(with_hand) == 1
    assert with_hand[0]["hand"] == "левая"
    assert "(" not in with_hand[0]["name"]


def test_tournament_search_parses_ajax_divs(load_fixture):
    result = parse_tournament_search(load_fixture("search_tournaments.html"))
    assert result["total_found"] == TOURNAMENT_SEARCH_CAP
    assert result["truncated"] is True
    first = result["tournaments"][0]
    assert first["id"] == "254e616"
    assert first["title"] == "Санкт Петербург. Турнир Энерджи АРЕНА"


def test_tournament_search_empty_response():
    result = parse_tournament_search("")
    assert result == {"total_found": 0, "truncated": False, "tournaments": []}


def test_no_matching_tournaments_is_empty_list():
    # Настоящий ответ сайта на поиск без совпадений.
    result = parse_tournament_search("<div>Никого не найдено.</div>")
    assert result == {"total_found": 0, "truncated": False, "tournaments": []}


def test_retired_ajax_action_raises():
    # admin-ajax отвечает "0" на несуществующее действие. Отличить это от
    # пустой выдачи обязательно: иначе отключённый эндпоинт читался бы как
    # «турниров нет», и модель сделала бы уверенный неверный вывод.
    with pytest.raises(ParseError):
        parse_tournament_search("0")
