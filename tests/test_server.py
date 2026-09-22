import pytest

from ttw_mcp import server
from ttw_mcp.errors import InvalidInput


class StubClient:
    def __init__(self, html: str = "") -> None:
        self.html = html
        self.calls: list[tuple] = []

    def get_html(self, path, params):
        self.calls.append(("GET", path, params))
        return self.html

    def post_ajax(self, action, **fields):
        self.calls.append(("POST", action, fields))
        return self.html


@pytest.fixture
def stub(monkeypatch):
    def install(html: str = "") -> StubClient:
        client = StubClient(html)
        monkeypatch.setattr(server, "_client", client)
        return client

    return install


@pytest.mark.parametrize("bad", ["", "   ", "\n"])
def test_search_players_rejects_empty_name(stub, bad):
    client = stub()
    with pytest.raises(InvalidInput):
        server.search_players(bad)
    assert client.calls == []  # запрос не ушёл: страница весит 6.7 МБ


@pytest.mark.parametrize("bad", ["", "ZZZZ", "1c18ed8!", "0123456789abcdef0"])
def test_get_player_rejects_malformed_id(stub, bad):
    client = stub()
    with pytest.raises(InvalidInput):
        server.get_player(bad)
    assert client.calls == []


def test_search_tournaments_requires_at_least_one_argument(stub):
    client = stub()
    with pytest.raises(InvalidInput):
        server.search_tournaments()
    assert client.calls == []


def test_get_player_requests_right_url_and_parses(stub, load_fixture):
    client = stub(load_fixture("player_novice.html"))
    result = server.get_player("1c18ed8")
    assert client.calls == [("GET", "/players/", {"id": "1c18ed8"})]
    assert result["name"] == "<игрок A>"
    assert len(result["matches"]) == 16


def test_search_players_passes_limit(stub, load_fixture):
    stub(load_fixture("search_players_two.html"))
    result = server.search_players("фомин", limit=1)
    assert result["total_found"] == 2
    assert len(result["players"]) == 1


def test_head_to_head_requests_with_parameter(stub, load_fixture):
    client = stub(load_fixture("head_to_head.html"))
    result = server.get_head_to_head("1c18ed8", "17828c3")
    assert client.calls == [("GET", "/players/", {"id": "1c18ed8", "with": "17828c3"})]
    assert result["opponent"]["name"] == "<игрок D>"


def test_get_tournament_parses(stub, load_fixture):
    client = stub(load_fixture("tournament.html"))
    result = server.get_tournament("6ad412a")
    assert client.calls == [("GET", "/tournaments/", {"id": "6ad412a"})]
    assert result["participants_count"] == 17


def test_search_tournaments_uses_ajax(stub, load_fixture):
    client = stub(load_fixture("search_tournaments.html"))
    result = server.search_tournaments(name="энерджи")
    assert client.calls[0][0] == "POST"
    assert client.calls[0][1] == "get_tournaments_by_name"
    assert result["truncated"] is True


def test_get_player_docstring_warns_about_window_and_lag():
    doc = server.get_player.__doc__
    assert "12" in doc
    assert "summary" in doc


def test_get_tournament_docstring_warns_there_are_no_matches():
    assert "матч" in server.get_tournament.__doc__.lower()
