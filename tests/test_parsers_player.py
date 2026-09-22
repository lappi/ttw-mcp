import re

import pytest

from ttw_mcp.errors import NotFound, ParseError
from ttw_mcp.parsers.player import _seed, parse_player_profile


@pytest.fixture
def novice(load_fixture):
    return parse_player_profile(load_fixture("player_novice.html"), "1c18ed8")


@pytest.fixture
def veteran(load_fixture):
    return parse_player_profile(load_fixture("player_veteran.html"), "66f1645")


def test_header_fields(novice):
    assert novice["player_id"] == "1c18ed8"
    assert novice["name"]
    assert novice["city"] == "--, -Санкт-Петербург"
    assert novice["rank"] == 91485


def test_current_rating_comes_from_newest_period_not_rounded_header(novice):
    # Шапка страницы показывает 84, ячейка последнего периода — 84.49.
    assert novice["current_rating"] == pytest.approx(84.49)


def test_summary_block(novice):
    summary = novice["summary"]
    assert summary["rated_periods"] == 3
    assert summary["tournaments_played"] == 2
    assert summary["rating_min"] == pytest.approx(84.48)
    assert summary["rating_max"] == pytest.approx(90.0)
    assert summary["rating_avg"] == pytest.approx(84.63)
    assert summary["games"] == 16
    assert summary["wins"] == 2
    assert summary["losses"] == 14
    assert summary["win_pct"] == 13


def test_summary_lags_one_period_behind_matches(veteran):
    # Системное расхождение сайта, а не ошибка парсинга: сводка не
    # включает самый свежий период, список матчей — включает.
    assert veteran["summary"]["games"] == 105
    assert len(veteran["matches"]) == 106


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
    assert "(" not in match["opponent_name"]
    assert match["opponent_rating"] == pytest.approx(206.48)
    assert match["delta"] == pytest.approx(0.0)


def test_win_is_marked_as_win(novice):
    wins = [m for m in novice["matches"] if m["result"] == "win"]
    assert len(wins) == 2
    assert {m["opponent_id"] for m in wins} == {
        "79429bb",
        "201fd1c",
    }


def test_empty_best_wins_is_empty_list_not_error(novice):
    assert novice["best_wins"] == []


def test_walkover_match_is_kept_not_dropped(veteran):
    # Техническую победу сайт пишет как "W:Тех" вместо счёта. Матч сыгран, у
    # него есть соперник и дельта, поэтому он остаётся в списке: исчезнув
    # молча, он занизил бы любой подсчёт игр, и заметить это было бы нечем.
    walkovers = [m for m in veteran["matches"] if m["result"] == "walkover_win"]
    assert len(walkovers) == 1
    only = walkovers[0]
    assert only["score_raw"] == "W:Тех"
    assert only["score_for"] is None
    assert only["score_against"] is None
    assert only["opponent_id"] == "730eb6d"
    assert "(" not in only["opponent_name"]
    assert only["opponent_rating"] == pytest.approx(143.72)


def test_veteran_has_full_twelve_month_window(veteran):
    assert veteran["name"]
    assert veteran["rank"] == 43767
    assert veteran["current_rating"] == pytest.approx(208.39)
    assert len(veteran["periods"]) == 13
    assert len(veteran["matches"]) == 106
    assert veteran["summary"]["wins"] == 76
    assert veteran["summary"]["losses"] == 29
    assert veteran["summary"]["win_pct"] == 72


def test_veteran_best_wins_parsed(veteran):
    best = veteran["best_wins"][0]
    assert best["date"] == "2026-06-28"
    assert best["tournament_id"] == "1ca9535"
    assert best["score_for"] == 3
    assert best["score_against"] == 1
    assert best["opponent_name"]
    assert best["opponent_rating"] == pytest.approx(312.0)
    assert best["delta"] == pytest.approx(4.60)


def test_the_two_fixtures_agree_about_their_shared_match(novice, veteran):
    # novice (1c18ed8) проиграл veteran (66f1645) 0:2; у veteran та же игра 2:0.
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


def test_missing_rating_in_opponent_name_raises(load_fixture):
    html = load_fixture("player_novice.html")
    link = re.search(r'<td class="game-name-cell"><a[^>]*>([^<]+)</a></td>', html)
    assert link is not None
    with_rating = link.group(1)
    without_rating = re.sub(r"\s*\([\d.]+\)$", "", with_rating)
    assert without_rating != with_rating
    broken = html.replace(with_rating, without_rating, 1)
    with pytest.raises(ParseError):
        parse_player_profile(broken, "1c18ed8")


def test_page_of_another_player_raises(load_fixture):
    broken = load_fixture("player_novice.html").replace(
        '<td class="player-id-cell" title="1c18ed8">1c18ed8</td>',
        '<td class="player-id-cell" title="deadbee">deadbee</td>',
    )
    with pytest.raises(ParseError):
        parse_player_profile(broken, "1c18ed8")


def test_all_walkover_forms_parse_on_real_profiles(load_fixture):
    # Формы распределены по двум профилям: ни один не содержит все четыре.
    loss = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    tech = parse_player_profile(load_fixture("player_walkover_tech.html"), "23a3d0d")

    def by_raw(profile, raw):
        return [m for m in profile["matches"] if m["score_raw"] == raw]

    assert len(by_raw(loss, "W:L")) == 1
    assert by_raw(loss, "W:L")[0]["result"] == "walkover_win"
    assert len(by_raw(loss, "L:W")) == 1
    assert by_raw(loss, "L:W")[0]["result"] == "walkover_loss"
    assert len(by_raw(tech, "Тех:W")) == 4
    assert all(m["result"] == "walkover_loss" for m in by_raw(tech, "Тех:W"))

    # Ни одного действительно неопознанного счёта на 2000 матчей.
    assert [m for m in loss["matches"] if m["result"] == "unparsed"] == []
    assert [m for m in tech["matches"] if m["result"] == "unparsed"] == []


def test_not_played_is_separated_from_losses(load_fixture):
    loss = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    void = [m for m in loss["matches"] if m["result"] == "not_played"]
    assert len(void) == 2
    assert all(m["score_raw"] == "0:0" for m in void)
    assert all(m["delta"] == 0.0 for m in void)


def test_hand_marker_is_split_out_of_opponent_names(load_fixture):
    # Двадцать одно вхождение из двадцати трёх живёт именно здесь, а не в поиске.
    profile = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    marked = [m for m in profile["matches"] if m["opponent_hand"]]
    assert len(marked) == 14
    assert sum(1 for m in marked if m["opponent_hand"] == "левая") == 8
    assert sum(1 for m in marked if m["opponent_hand"] == "правая") == 6
    assert all("(" not in m["opponent_name"] for m in marked)
    assert all(m["opponent_hand"] in ("левая", "правая") for m in marked)


def test_hand_marker_in_walkover_tech_matches(load_fixture):
    profile = parse_player_profile(load_fixture("player_walkover_tech.html"), "23a3d0d")
    marked = [m for m in profile["matches"] if m["opponent_hand"]]
    assert len(marked) == 4
    assert all(m["opponent_hand"] == "левая" for m in marked)
    assert all("(" not in m["opponent_name"] for m in marked)


def test_hand_marker_absent_from_own_name_and_best_wins(novice, veteran, load_fixture):
    # На всех четырёх профилях пометка руки не встречается ни в собственном
    # имени игрока, ни в блоке «Лучшие победы» — только в списке матчей.
    loss = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    tech = parse_player_profile(load_fixture("player_walkover_tech.html"), "23a3d0d")
    for profile in (novice, veteran, loss, tech):
        assert profile["hand"] is None
        assert all(w["opponent_hand"] is None for w in profile["best_wins"])


def test_hand_marker_count_on_veteran_and_novice_matches(novice, veteran):
    # Поправка 5: обе фикстуры дают ровно одно совпадение, «левая».
    for profile in (novice, veteran):
        marked = [m for m in profile["matches"] if m["opponent_hand"]]
        assert len(marked) == 1
        assert marked[0]["opponent_hand"] == "левая"
        assert "(" not in marked[0]["opponent_name"]


def test_seed_rating_is_reconstructed_from_the_earliest_period(novice, veteran):
    # rating_after самого раннего периода минус его дельта. Метод даёт
    # круглые значения, что его и подтверждает: система сажает новичка
    # на целое число.
    assert novice["summary"]["seed_rating"] == pytest.approx(90.00)
    assert novice["summary"]["first_rated_date"] == "2026-09-07"
    assert veteran["summary"]["seed_rating"] == pytest.approx(115.00)
    assert veteran["summary"]["first_rated_date"] == "2025-09-15"


def test_seed_rating_survives_the_rated_periods_cap(load_fixture):
    # У этих игроков rated_periods упёрлось в потолок 30, но таблица
    # периодов показана целиком — 87 и 91 период, и ни одного матча
    # раньше начала самого раннего из них. Стартовый рейтинг
    # восстанавливается, и он целый, как и положено.
    deep = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    assert deep["summary"]["rated_periods"] == 30
    assert len(deep["periods"]) == 87
    assert deep["summary"]["seed_rating"] == pytest.approx(80.00)
    assert deep["summary"]["first_rated_date"] == "2023-12-25"

    tech = parse_player_profile(load_fixture("player_walkover_tech.html"), "23a3d0d")
    assert tech["summary"]["rated_periods"] == 30
    assert len(tech["periods"]) == 91
    assert tech["summary"]["seed_rating"] == pytest.approx(50.00)
    assert tech["summary"]["first_rated_date"] == "2024-05-27"


def test_seed_is_unknown_without_periods():
    assert _seed([], [{"date": "2024-01-01"}]) == (None, None)


def test_seed_is_unknown_when_a_match_predates_the_earliest_period():
    # Матч раньше начала самого раннего периода означает, что таблица
    # периодов показана не целиком, и восстанавливать по ней нечего.
    periods = [{"start": "2024-01-01", "end": "2024-01-07", "rating_after": 100.0, "delta": 10.0}]
    assert _seed(periods, [{"date": "2023-12-31"}]) == (None, None)
    assert _seed(periods, [{"date": "2024-01-02"}]) == (90.0, "2024-01-01")


def test_matches_can_be_omitted_but_the_count_survives(load_fixture):
    # 93 % объёма профиля — это matches. Но выкинуть их молча нельзя:
    # модель не отличит «сыграл 12» от «показали 12 из 1891».
    slim = parse_player_profile(
        load_fixture("player_veteran.html"), "66f1645", include_matches=False
    )
    assert "matches" not in slim
    assert "best_wins" not in slim
    assert slim["matches_total"] == 106
    assert slim["best_wins_total"] == 5
    assert len(slim["periods"]) == 13


def test_matches_since_filters_but_reports_the_whole(load_fixture):
    recent = parse_player_profile(
        load_fixture("player_veteran.html"), "66f1645", matches_since="2026-09-01"
    )
    assert recent["matches_total"] == 106
    assert len(recent["matches"]) == 7
    assert all(m["date"] >= "2026-09-01" for m in recent["matches"])
