import pytest

from ttw_mcp.parsers.player import parse_player_profile
from ttw_mcp.rating import annotate_matches, rating_at_event


@pytest.fixture
def novice(load_fixture):
    return parse_player_profile(load_fixture("player_novice.html"), "1c18ed8")


@pytest.fixture
def deep(load_fixture):
    return parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")


@pytest.fixture
def tech(load_fixture):
    return parse_player_profile(load_fixture("player_walkover_tech.html"), "23a3d0d")


def test_rating_at_event_differs_from_the_current_one(novice):
    # Турнир 6ad412a прошёл 2026-09-13. Таблица турнира показывает для этого
    # игрока его СЕГОДНЯШНИЙ рейтинг, а на момент турнира было 90.00.
    # Ради этой разницы инструмент и существует.
    assert rating_at_event(novice, "2026-09-13") == pytest.approx(90.00)
    assert novice["current_rating"] == pytest.approx(84.49)


def test_rating_at_event_is_none_outside_known_history(novice):
    assert rating_at_event(novice, "2020-01-01") is None


def test_rating_at_event_matches_what_the_site_recorded_in_match_rows(deep, tech):
    # Независимая проверка формулы: сайт сам пишет в строке матча рейтинг
    # соперника ДО турнира. Эти двое встречались восемь раз, и восстановленный
    # рейтинг 23a3d0d обязан совпасть с тем, что записано в матчах 44d227e.
    meetings = [m for m in deep["matches"] if m["opponent_id"] == "23a3d0d"]
    assert len(meetings) == 8
    for match in meetings:
        assert rating_at_event(tech, match["date"]) == pytest.approx(
            match["opponent_rating"]
        ), match["date"]


def test_rating_at_event_subtracts_later_tournaments_of_the_same_period(deep):
    # Период 2025-12-08..2025-12-14 завершился на 183.83 и содержит два
    # турнира: 2025-12-11 (+0.14) и 2025-12-14 (−3.87). Перед первым из них
    # рейтинг был выше итогового на сумму обеих дельт, перед вторым — только
    # на его собственную.
    assert rating_at_event(deep, "2025-12-11") == pytest.approx(187.56)
    assert rating_at_event(deep, "2025-12-14") == pytest.approx(187.70)


def test_rating_at_event_is_none_when_two_tournaments_share_the_day(deep, tech):
    # Сайт не сообщает порядок турниров внутри дня, поэтому вычесть нужные
    # дельты нельзя. Честный None вместо правдоподобного приближения.
    assert rating_at_event(deep, "2023-12-30") is None
    assert rating_at_event(tech, "2024-12-28") is None


def test_annotate_matches_fills_every_match(novice):
    annotate_matches(novice)
    assert all("player_rating_at_match" in m for m in novice["matches"])
    for match in novice["matches"]:
        if match["date"] == "2026-09-13":
            assert match["player_rating_at_match"] == pytest.approx(90.00)


def test_annotate_matches_leaves_none_on_ambiguous_days(deep):
    annotate_matches(deep)
    ambiguous = [m for m in deep["matches"] if m["date"] == "2023-12-30"]
    assert len(ambiguous) == 12
    assert all(m["player_rating_at_match"] is None for m in ambiguous)
