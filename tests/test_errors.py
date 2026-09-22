import pytest

from ttw_mcp.errors import (
    InvalidInput,
    NotFound,
    ParseError,
    TtwError,
    UpstreamError,
)


def test_parse_error_names_parser_and_selector():
    err = ParseError("parse_player_profile", "div.player-page h1 span")
    assert "parse_player_profile" in str(err)
    assert "div.player-page h1 span" in str(err)


def test_parse_error_includes_detail_when_given():
    err = ParseError("parse_tournament", ".tournament-date-cell", "пустая таблица")
    assert "пустая таблица" in str(err)


def test_upstream_error_names_url_and_reason():
    err = UpstreamError("https://r.ttw.ru/players/?id=1c18ed8", "timeout 30.0s")
    assert "https://r.ttw.ru/players/?id=1c18ed8" in str(err)
    assert "timeout 30.0s" in str(err)


@pytest.mark.parametrize("cls", [InvalidInput, NotFound, ParseError, UpstreamError])
def test_all_errors_share_common_ancestor(cls):
    assert issubclass(cls, TtwError)
