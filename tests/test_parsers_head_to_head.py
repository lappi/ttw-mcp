import pytest

from ttw_mcp.errors import ParseError
from ttw_mcp.parsers.head_to_head import parse_head_to_head


@pytest.fixture
def h2h(load_fixture):
    return parse_head_to_head(load_fixture("head_to_head.html"), "1c18ed8", "17828c3")


def test_both_sides_identified(h2h):
    assert h2h["player"]["id"] == "1c18ed8"
    assert h2h["player"]["name"]
    assert h2h["opponent"]["id"] == "17828c3"
    assert h2h["opponent"]["name"]


def test_ratings_and_ranks(h2h):
    # На этой странице рейтинг округлён до целого — два знака она не даёт.
    assert h2h["player"]["current_rating"] == pytest.approx(84.0)
    assert h2h["player"]["rank"] == 91485
    assert h2h["opponent"]["current_rating"] == pytest.approx(70.0)
    assert h2h["opponent"]["rank"] == 96020


def test_win_and_set_counts(h2h):
    assert h2h["wins"] == {"player": 0, "opponent": 1}
    assert h2h["win_pct"] == {"player": 0, "opponent": 100}
    assert h2h["sets"] == {"player": 1, "opponent": 2}
    assert h2h["sets_pct"] == {"player": 33, "opponent": 67}


def test_mutual_matches(h2h):
    assert len(h2h["matches"]) == 1
    match = h2h["matches"][0]
    assert match["date"] == "2026-09-13"
    assert match["tournament_id"] == "6ad412a"
    assert match["tournament_title"] == "Санкт Петербург. Турнир Энерджи Арена."
    assert match["score_raw"] == "1:2"
    assert match["player_score"] == 1
    assert match["opponent_score"] == 2


def test_walkover_in_head_to_head_is_kept(load_fixture):
    # 66f1645 против 730eb6d: три встречи, одна присуждена технически.
    # Раньше int("W") здесь падал, и это была не гипотеза — страница живая.
    h2h = parse_head_to_head(
        load_fixture("head_to_head_walkover.html"), "66f1645", "730eb6d"
    )
    assert h2h["player"]["id"] == "66f1645"
    assert h2h["player"]["name"]
    assert h2h["opponent"]["id"] == "730eb6d"
    assert h2h["opponent"]["name"]
    assert len(h2h["matches"]) == 3
    walkovers = [m for m in h2h["matches"] if m["score_raw"] == "W:Тех"]
    assert len(walkovers) == 1
    assert walkovers[0]["player_score"] is None
    assert walkovers[0]["opponent_score"] is None


def test_broken_markup_raises_parse_error():
    with pytest.raises(ParseError):
        parse_head_to_head("<html><body>пусто</body></html>", "a", "b")


def test_players_who_never_met_give_empty_matches(load_fixture):
    # Самый частый запрос модели. Страница рендерит блоки с нулями, а не
    # опускает их, поэтому ParseError здесь быть не должно.
    h2h = parse_head_to_head(load_fixture("head_to_head_never_met.html"), "1c18ed8", "7063200")
    assert h2h["matches"] == []
    assert h2h["wins"] == {"player": 0, "opponent": 0}
    assert h2h["player"]["id"] == "1c18ed8"
    assert h2h["player"]["name"]
    assert h2h["opponent"]["id"] == "7063200"
    assert h2h["opponent"]["name"]
