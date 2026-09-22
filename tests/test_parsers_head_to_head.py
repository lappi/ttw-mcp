import pytest

from ttw_mcp.errors import ParseError
from ttw_mcp.parsers.head_to_head import parse_head_to_head


@pytest.fixture
def h2h(load_fixture):
    return parse_head_to_head(load_fixture("head_to_head.html"), "1c18ed8", "17828c3")


def test_both_sides_identified(h2h):
    assert h2h["player"]["id"] == "1c18ed8"
    assert h2h["player"]["name"] == "<игрок A>"
    assert h2h["opponent"]["id"] == "17828c3"
    assert h2h["opponent"]["name"] == "<игрок D>"


def test_ratings_and_ranks(h2h):
    # На этой странице рейтинг округлён до целого — два знака она не даёт.
    assert h2h["player"]["current_rating"] == pytest.approx(84.0)
    assert h2h["player"]["rank"] == 91380
    assert h2h["opponent"]["current_rating"] == pytest.approx(70.0)
    assert h2h["opponent"]["rank"] == 95980


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
    assert match["player_score"] == 1
    assert match["opponent_score"] == 2


def test_broken_markup_raises_parse_error():
    with pytest.raises(ParseError):
        parse_head_to_head("<html><body>пусто</body></html>", "a", "b")
