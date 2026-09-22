import pytest

from ttw_mcp.errors import NotFound, ParseError
from ttw_mcp.parsers.player import parse_player_profile


@pytest.fixture
def novice(load_fixture):
    return parse_player_profile(load_fixture("player_novice.html"), "1c18ed8")


@pytest.fixture
def veteran(load_fixture):
    return parse_player_profile(load_fixture("player_veteran.html"), "66f1645")


def test_header_fields(novice):
    assert novice["player_id"] == "1c18ed8"
    assert novice["name"] == "<игрок A>"
    assert novice["city"] == "--, -Санкт-Петербург"
    assert novice["rank"] == 91380


def test_current_rating_comes_from_newest_period_not_rounded_header(novice):
    # Шапка страницы показывает 84, ячейка последнего периода — 84.49.
    assert novice["current_rating"] == pytest.approx(84.49)


def test_summary_block(novice):
    summary = novice["summary"]
    assert summary["rated_periods"] == 2
    assert summary["tournaments_played"] == 1
    assert summary["rating_min"] == pytest.approx(84.78)
    assert summary["rating_max"] == pytest.approx(90.0)
    assert summary["rating_avg"] == pytest.approx(84.78)
    assert summary["games"] == 9
    assert summary["wins"] == 0
    assert summary["losses"] == 9
    assert summary["win_pct"] == 0


def test_summary_lags_one_period_behind_matches(novice):
    # Системное расхождение сайта, а не ошибка парсинга: сводка не
    # включает самый свежий период, список матчей — включает.
    assert novice["summary"]["games"] == 9
    assert len(novice["matches"]) == 16


def test_periods(novice):
    assert len(novice["periods"]) == 2
    first = novice["periods"][0]
    assert first["start"] == "2026-09-14"
    assert first["end"] == "2026-09-20"
    assert first["rating_after"] == pytest.approx(84.49)
    assert first["delta"] == pytest.approx(-0.29)


def test_tournaments(novice):
    assert len(novice["tournaments"]) == 2
    first = novice["tournaments"][0]
    assert first["date"] == "2026-09-20"
    assert first["tournament_id"] == "5f73688"
    assert first["title"] == "Санкт Петербург. Турнир Энерджи Арена"
    assert first["delta"] == pytest.approx(-0.29)


def test_first_match_fully_parsed(novice):
    match = novice["matches"][0]
    assert match["date"] == "2026-09-20"
    assert match["tournament_id"] == "5f73688"
    assert match["score_raw"] == "0:2"
    assert match["score_for"] == 0
    assert match["score_against"] == 2
    assert match["result"] == "loss"
    assert match["opponent_id"] == "66f1645"
    assert match["opponent_name"] == "<игрок B>"
    assert match["opponent_rating"] == pytest.approx(206.48)
    assert match["delta"] == pytest.approx(0.0)


def test_win_is_marked_as_win(novice):
    wins = [m for m in novice["matches"] if m["result"] == "win"]
    assert len(wins) == 2
    assert {m["opponent_name"] for m in wins} == {
        "<игрок F>",
        "<игрок C>",
    }


def test_empty_best_wins_is_empty_list_not_error(novice):
    assert novice["best_wins"] == []


def test_walkover_match_is_kept_not_dropped(veteran):
    # Техническую победу сайт пишет как "W:Тех" вместо счёта. Матч сыгран, у
    # него есть соперник и дельта, поэтому он остаётся в списке: исчезнув
    # молча, он занизил бы любой подсчёт игр, и заметить это было бы нечем.
    walkovers = [m for m in veteran["matches"] if m["result"] == "walkover"]
    assert len(walkovers) == 1
    only = walkovers[0]
    assert only["score_raw"] == "W:Тех"
    assert only["score_for"] is None
    assert only["score_against"] is None
    assert only["opponent_name"] == "<игрок E>"
    assert only["opponent_rating"] == pytest.approx(143.72)


def test_veteran_has_full_twelve_month_window(veteran):
    assert veteran["name"] == "<игрок B>"
    assert veteran["rank"] == 44245
    assert veteran["current_rating"] == pytest.approx(208.39)
    assert len(veteran["periods"]) == 13
    assert len(veteran["matches"]) == 106
    assert veteran["summary"]["wins"] == 71
    assert veteran["summary"]["losses"] == 27
    assert veteran["summary"]["win_pct"] == 72


def test_veteran_best_wins_parsed(veteran):
    best = veteran["best_wins"][0]
    assert best["date"] == "2026-06-28"
    assert best["tournament_id"] == "1ca9535"
    assert best["score_for"] == 3
    assert best["score_against"] == 1
    assert best["opponent_name"] == "<игрок G>"
    assert best["opponent_rating"] == pytest.approx(312.0)
    assert best["delta"] == pytest.approx(4.60)


def test_the_two_fixtures_agree_about_their_shared_match(novice, veteran):
    # <игрок A> проиграл <игрок B> 0:2; у <игрок B> та же игра 2:0.
    theirs = [m for m in veteran["matches"] if m["opponent_id"] == "1c18ed8"][0]
    ours = [m for m in novice["matches"] if m["opponent_id"] == "66f1645"][0]
    assert (ours["score_for"], ours["score_against"]) == (0, 2)
    assert (theirs["score_for"], theirs["score_against"]) == (2, 0)


def test_unknown_player_raises_not_found(load_fixture):
    with pytest.raises(NotFound):
        parse_player_profile(load_fixture("player_not_found.html"), "deadbee")


def test_broken_markup_raises_parse_error():
    with pytest.raises(ParseError):
        parse_player_profile("<html><body>ничего похожего</body></html>", "1c18ed8")
