import pytest

from ttw_mcp.errors import ParseError
from ttw_mcp.parsers.common import (
    clean,
    extract_id,
    parse_date,
    parse_int,
    parse_number,
    parse_score,
    parse_win_loss,
    require,
    split_hand,
)


def test_clean_collapses_whitespace_and_nbsp():
    assert clean("  один\xa0 два\n три ") == "один два три"


@pytest.mark.parametrize(
    "raw,expected",
    [("13.09.2026", "2026-09-13"), ("05.07.2026", "2026-07-05"), ("02.11.2024", "2024-11-02")],
)
def test_parse_date_converts_to_iso(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_rejects_garbage():
    with pytest.raises(ParseError):
        parse_date("не дата")


@pytest.mark.parametrize(
    "raw,expected",
    [("+1.41", 1.41), ("-0.29", -0.29), ("0.00", 0.0), ("134", 134.0), ("84.78", 84.78)],
)
def test_parse_number_handles_signs(raw, expected):
    assert parse_number(raw) == pytest.approx(expected)


def test_parse_int_strips_percent_and_spaces():
    assert parse_int(" 72% ") == 72
    assert parse_int("91380") == 91380


def test_parse_win_loss_splits_pair():
    assert parse_win_loss("0-9") == (0, 9)
    assert parse_win_loss("71-27") == (71, 27)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3:1", (3, 1, "win")),
        ("0:2", (0, 2, "loss")),
        ("W:Тех", (None, None, "walkover_win")),
        ("W:L", (None, None, "walkover_win")),
        ("Тех:W", (None, None, "walkover_loss")),
        ("L:W", (None, None, "walkover_loss")),
        ("0:0", (None, None, "not_played")),
        ("3-1", (None, None, "unparsed")),
        ("", (None, None, "unparsed")),
    ],
)
def test_parse_score_knows_every_observed_form(raw, expected):
    # Четыре формы технического результата и «не сыгран» замерены на 4621
    # матче. Раньше три из них уходили в unparsed, и докстринг отправлял
    # пользователя искать изменившуюся вёрстку там, где её не было.
    assert parse_score(raw) == expected


@pytest.mark.parametrize(
    "href,expected",
    [
        ("/players/?id=1c18ed8", "1c18ed8"),
        ("/tournaments/?id=6ad412a", "6ad412a"),
        ("/players/?id=1c18ed8&with=17828c3", "1c18ed8"),
    ],
)
def test_extract_id_reads_id_param(href, expected):
    assert extract_id(href) == expected


def test_extract_id_rejects_missing_id():
    with pytest.raises(ParseError):
        extract_id("/players/")


def test_require_raises_named_parse_error_on_none():
    with pytest.raises(ParseError) as excinfo:
        require(None, "div.player-page h1 span", "parse_player_profile")
    assert "parse_player_profile" in str(excinfo.value)
    assert "div.player-page h1 span" in str(excinfo.value)


def test_require_passes_node_through():
    sentinel = object()
    assert require(sentinel, "div", "parser") is sentinel


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Фамилия Имя Отчество", ("Фамилия Имя Отчество", None)),
        ("Неправая Имя Отчество", ("Неправая Имя Отчество", None)),
        ("Фамилия Имя Отчество левая", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество (левая)", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество (правая)", ("Фамилия Имя Отчество", "правая")),
        ("Фамилия(правая) Имя Отчество", ("Фамилия Имя Отчество", "правая")),
        ("Фамилия Имя Отчество(левая)", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество ( левая)", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество (левая рука)", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество (левая руков)", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество ( левая/шипы)", ("Фамилия Имя Отчество (шипы)", "левая")),
        ("Фамилия Левая Отчество", ("Фамилия Отчество", "левая")),
        ("Фамилия Имя Левая", ("Фамилия Имя", "левая")),
        ("Фамилия Левая Рукимя", ("Фамилия Рукимя", "левая")),
    ],
)
def test_split_hand_handles_every_measured_form(raw, expected):
    # Четырнадцать форм замерены на 2835 именах из фикстур; случай со
    # «шипами» проверяет, что остаток заметки не выбрасывается вместе с рукой.
    assert split_hand(raw) == expected
