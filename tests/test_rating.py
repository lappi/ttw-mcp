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


def test_annotate_matches_covers_best_wins_too(load_fixture):
    # У лучших побед сайт показывает собственный рейтинг игрока
    # сегодняшний, а рейтинг соперника — на момент встречи. Сопоставить
    # стороны можно только по восстановленному значению.
    profile = parse_player_profile(load_fixture("player_veteran.html"), "66f1645")
    annotate_matches(profile)
    expected = {
        "2026-06-13": 175.17,
        "2026-06-28": 181.66,
        "2026-08-16": 194.18,
        "2026-08-23": 200.60,
    }
    # Без схлопывания в словарь по дате: 2026-06-28 в списке встречается
    # дважды (две лучшие победы в один день), и проверка каждой записи
    # по отдельности доказывает, что обе получили одно и то же значение,
    # а не что в словаре просто осталась последняя из двух.
    for win in profile["best_wins"]:
        assert win["player_rating_at_match"] == pytest.approx(
            expected[win["date"]]
        ), win["date"]
    same_day = [w for w in profile["best_wins"] if w["date"] == "2026-06-28"]
    assert len(same_day) == 2
    assert all(w["player_rating_at_match"] == pytest.approx(181.66) for w in same_day)


def test_best_wins_keep_the_site_value_under_an_honest_name(load_fixture):
    # 208.0 — это сегодняшний рейтинг игрока (208.39), а не рейтинг на
    # момент победы. Имя обязано это говорить.
    profile = parse_player_profile(load_fixture("player_veteran.html"), "66f1645")
    assert all("player_rating" not in w for w in profile["best_wins"])
    assert {w["player_rating_current"] for w in profile["best_wins"]} == {208.0}
    assert profile["current_rating"] == pytest.approx(208.39)


def test_unresolved_ratings_are_only_the_ambiguous_days(deep):
    # 207 матчей из 1127 остаются без рейтинга, и все до единого — в даты,
    # когда игрок сыграл два турнира. Ни один не выпал из-за дыры в истории.
    annotate_matches(deep)
    unresolved = [m for m in deep["matches"] if m["player_rating_at_match"] is None]
    assert len(unresolved) == 207
    crowded = {
        t["date"]
        for t in deep["tournaments"]
        if sum(1 for x in deep["tournaments"] if x["date"] == t["date"]) > 1
    }
    assert all(m["date"] in crowded for m in unresolved)
