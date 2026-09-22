import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from ttw_mcp import server


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
    # search_players несёт @_reporting, поэтому даже прямой вызов вместо
    # исходного InvalidInput получает ToolError с его именем внутри — это
    # тот же перевод, что видит модель через MCP.
    client = stub()
    with pytest.raises(ToolError, match="InvalidInput"):
        server.search_players(bad)
    assert client.calls == []  # запрос не ушёл: страница весит 6.7 МБ


@pytest.mark.parametrize(
    "bad", ["", "ZZZZ", "1c18ed8!", "0123456789abcdef0", "1c18ed8\n"]
)
def test_get_player_rejects_malformed_id(stub, bad):
    client = stub()
    with pytest.raises(ToolError, match="InvalidInput"):
        server.get_player(bad)
    assert client.calls == []


def test_search_tournaments_requires_at_least_one_argument(stub):
    client = stub()
    with pytest.raises(ToolError, match="InvalidInput"):
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
    # Подстрочные проверки вроде `"12" in doc` проходят и на докстринге,
    # утверждающем обратное, поэтому сверяемся с формулировками, которые
    # нельзя удовлетворить противоположным по смыслу текстом.
    doc = server.get_player.__doc__
    assert "12 месяцев" in doc
    assert "summary" in doc and "отстаёт" in doc
    assert "используйте matches" in doc
    assert "walkover" in doc


def test_get_tournament_docstring_warns_there_are_no_matches():
    doc = server.get_tournament.__doc__
    assert "только итоговую таблицу" in doc
    assert "Отдельных матчей" in doc
    assert "get_player" in doc


def test_search_players_docstring_explains_limit_versus_total():
    doc = server.search_players.__doc__
    assert "truncated" in doc
    assert "total_found" in doc and "limit" in doc


def test_errors_reach_the_model_through_mcp(stub):
    # Прямой вызов функции этот путь не проверяет: стирание происходит
    # в SDK, между инструментом и моделью.
    stub()
    manager = server.mcp._tool_manager

    async def call(name, args):
        try:
            await manager.call_tool(name, args, None)
        except Exception as exc:  # noqa: BLE001 — нас интересует сам объект
            return exc
        return None

    error = asyncio.run(call("get_player", {"player_id": "zz"}))

    # UnexpectedToolError наследует ToolError, а __cause__ SDK выставляет на
    # исходное исключение в обоих случаях. Поэтому ни isinstance(error,
    # ToolError), ни обход цепочки до TtwError ничего не различают — они
    # проходят и на коде без _reporting. Различают ровно две вещи: что это
    # не крах, и что подробности дошли до текста, который увидит модель.
    assert not isinstance(error, UnexpectedToolError)
    assert "InvalidInput" in str(error)
    assert "player_id" in str(error)
