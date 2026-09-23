import pytest

CASES = [
    ("player_novice.html", "1c18ed8"),
    ("player_veteran.html", 'class="player-game-tournament-cell"'),
    ("player_not_found.html", 'class="layout-row player-page"'),
    ("head_to_head.html", "Противостояние"),
    ("head_to_head_walkover.html", "W:Тех"),
    ("tournament.html", "Санкт Петербург. Турнир Энерджи Арена"),
    ("search_players_many.html", "104aa33"),
    ("search_players_capped.html", "player-name-cell"),
    ("search_tournaments.html", "/tournaments/?id="),
    ("head_to_head_never_met.html", "Противостояние"),
    ("search_players_zero.html", "player-list"),
    ("player_walkover_loss.html", "44d227e"),
    ("player_walkover_tech.html", "23a3d0d"),
    ("player_participant.html", "17828c3"),
]


@pytest.mark.parametrize("name,anchor", CASES)
def test_fixture_loads_and_contains_anchor(load_fixture, name, anchor):
    html = load_fixture(name)
    assert len(html) > 1000
    assert anchor in html


def test_capped_search_fixture_has_500_rows(load_fixture):
    html = load_fixture("search_players_capped.html")
    assert html.count("player-name-cell") == 500
