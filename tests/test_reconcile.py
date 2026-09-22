"""Тесты сведения матчей турнира `ttw_mcp.reconcile.reconcile_matches`."""

import pytest

from ttw_mcp.errors import ParseError
from ttw_mcp.reconcile import reconcile_matches


def _row(opponent_id, score_for, score_against, result, tournament_id="ttt9999", date="2026-01-18"):
    return {
        "date": date,
        "tournament_id": tournament_id,
        "opponent_id": opponent_id,
        "score_raw": f"{score_for}:{score_against}",
        "score_for": score_for,
        "score_against": score_against,
        "result": result,
        "delta": 0.0,
    }


def test_reconcile_keeps_both_meetings_of_the_same_pair():
    # Групповой этап плюс плей-офф: пара играет дважды за день. Замерено,
    # что так бывает в шестнадцати днях у каждого из двух глубоких профилей.
    profiles = {
        "aaa1111": {"matches": [_row("bbb2222", 2, 0, "win"), _row("bbb2222", 1, 2, "loss")]},
        "bbb2222": {"matches": [_row("aaa1111", 0, 2, "loss"), _row("aaa1111", 2, 1, "win")]},
    }
    assert len(reconcile_matches(profiles, "ttt9999")) == 2


def test_reconcile_keeps_two_identical_scores():
    # Два матча с одинаковым счётом тоже бывают: различить их нечем,
    # и схлопывать их в один было бы потерей матча.
    profiles = {
        "aaa1111": {"matches": [_row("bbb2222", 0, 3, "loss"), _row("bbb2222", 0, 3, "loss")]},
        "bbb2222": {"matches": [_row("aaa1111", 3, 0, "win"), _row("aaa1111", 3, 0, "win")]},
    }
    assert len(reconcile_matches(profiles, "ttt9999")) == 2


def test_reconcile_passes_through_one_sided_rows():
    # Профиль соперника не собран — отдаём то, что есть, и не выдумываем.
    profiles = {"aaa1111": {"matches": [_row("bbb2222", 2, 0, "win")]}}
    matches = reconcile_matches(profiles, "ttt9999")
    assert len(matches) == 1
    assert matches[0]["player_id"] == "aaa1111"


def test_reconcile_raises_when_the_two_sides_disagree():
    profiles = {
        "aaa1111": {"matches": [_row("bbb2222", 2, 0, "win")]},
        "bbb2222": {"matches": [_row("aaa1111", 1, 2, "loss")]},
    }
    with pytest.raises(ParseError):
        reconcile_matches(profiles, "ttt9999")


def test_reconcile_mirrors_walkovers_by_result():
    # У технического результата партий нет, и без сверки исхода
    # техническая победа «зеркалила» бы техническую победу.
    win = _row("bbb2222", None, None, "walkover_win")
    win["score_raw"] = "W:Тех"
    loss = _row("aaa1111", None, None, "walkover_loss")
    loss["score_raw"] = "Тех:W"
    assert len(reconcile_matches({"aaa1111": {"matches": [win]}, "bbb2222": {"matches": [loss]}}, "ttt9999")) == 1

    both_win = _row("aaa1111", None, None, "walkover_win")
    both_win["score_raw"] = "W:Тех"
    with pytest.raises(ParseError):
        reconcile_matches(
            {"aaa1111": {"matches": [win]}, "bbb2222": {"matches": [both_win]}},
            "ttt9999",
        )


def test_reconcile_mirrors_not_played_by_result():
    # not_played зеркалит сам себя: несыгранный матч выглядит одинаково
    # с обеих сторон, счёта 0:0 у обеих. Строка таблицы _MIRROR для этого
    # исхода иначе не проверена ничем.
    left = _row("bbb2222", None, None, "not_played")
    left["score_raw"] = "0:0"
    right = _row("aaa1111", None, None, "not_played")
    right["score_raw"] = "0:0"
    matches = reconcile_matches({"aaa1111": {"matches": [left]}, "bbb2222": {"matches": [right]}}, "ttt9999")
    assert len(matches) == 1


def test_reconcile_mirrors_unparsed_by_result():
    # unparsed — признак изменившейся вёрстки, но раз уж обе стороны дали
    # такую запись с совпадающим (пустым) счётом, зеркало для неё в
    # таблице _MIRROR тоже обязано находиться, а не падать с KeyError.
    left = _row("bbb2222", None, None, "unparsed")
    left["score_raw"] = "?"
    right = _row("aaa1111", None, None, "unparsed")
    right["score_raw"] = "?"
    matches = reconcile_matches({"aaa1111": {"matches": [left]}, "bbb2222": {"matches": [right]}}, "ttt9999")
    assert len(matches) == 1


def test_reconcile_ignores_another_tournament_on_the_same_day():
    # Участник сыграл в тот же день второй турнир. Его матчи оттуда не
    # должны попасть в выдачу: при отборе по дате они выглядели бы
    # обычной зеркальной парой и молча увеличили бы число матчей турнира.
    profiles = {
        "aaa1111": {
            "matches": [
                _row("bbb2222", 2, 0, "win"),
                _row("ccc3333", 2, 1, "win", tournament_id="uuu8888"),
            ]
        },
        "bbb2222": {"matches": [_row("aaa1111", 0, 2, "loss")]},
        "ccc3333": {"matches": [_row("aaa1111", 1, 2, "loss", tournament_id="uuu8888")]},
    }
    matches = reconcile_matches(profiles, "ttt9999")
    assert len(matches) == 1
    assert {matches[0]["player_id"], matches[0]["opponent_id"]} == {"aaa1111", "bbb2222"}
