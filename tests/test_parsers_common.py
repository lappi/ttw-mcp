import pytest

from ttw_mcp.errors import ParseError
from ttw_mcp.parsers.common import (
    clean,
    extract_id,
    parse_date,
    parse_int,
    parse_number,
    parse_win_loss,
    require,
)


def test_clean_collapses_whitespace_and_nbsp():
    assert clean("  <игрок\xa0 A\n тестовый> ") == "<игрок A>"


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
