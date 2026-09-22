import asyncio
import re

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from ttw_mcp import server
from ttw_mcp.errors import NotFound


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


@pytest.fixture
def stub_multi(monkeypatch):
    def install(pages: dict[str, str]):
        class MultiStub:
            def __init__(self):
                self.calls = []

            def get_html(self, path, params):
                key = params["id"]
                self.calls.append(key)
                if key not in pages:
                    raise NotFound(f"нет страницы для {key}")
                return pages[key]

        client = MultiStub()
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
    assert result["player_id"] == "1c18ed8"
    assert result["name"]
    assert len(result["matches"]) == 16


def test_matches_carry_the_players_own_rating(stub, load_fixture):
    # Рейтинг соперника сайт даёт, свой — нет. Без него матч нельзя
    # сопоставить по силе сторон, и в полевом отчёте датасет на 169 матчей
    # собирался вручную именно из-за этого.
    stub(load_fixture("player_novice.html"))
    result = server.get_player("1c18ed8")
    assert all("player_rating_at_match" in m for m in result["matches"])
    assert all(m["player_rating_at_match"] is not None for m in result["matches"])
    assert {m["player_rating_at_match"] for m in result["matches"]} == {84.78, 90.00}


def test_search_players_passes_limit(stub, load_fixture):
    stub(load_fixture("search_players_many.html"))
    result = server.search_players("фомин", limit=1)
    assert result["total_found"] == 177
    assert len(result["players"]) == 1


def test_head_to_head_requests_with_parameter(stub, load_fixture):
    client = stub(load_fixture("head_to_head.html"))
    result = server.get_head_to_head("1c18ed8", "17828c3")
    assert client.calls == [("GET", "/players/", {"id": "1c18ed8", "with": "17828c3"})]
    assert result["opponent"]["id"] == "17828c3"
    assert result["opponent"]["name"]


def test_get_tournament_parses(stub, load_fixture):
    client = stub(load_fixture("tournament.html"))
    result = server.get_tournament("6ad412a")
    assert client.calls == [("GET", "/tournaments/", {"id": "6ad412a"})]
    assert result["participants_count"] == 17


def test_ratings_at_event_differ_from_current(stub_multi, load_fixture):
    # Турнир 2026-09-13. В таблице у этого игрока стоит 84.48 — сегодняшнее
    # значение. На момент турнира было 90.00. Разница и есть предмет правки.
    client = stub_multi(
        {"6ad412a": load_fixture("tournament.html"),
         "1c18ed8": load_fixture("player_novice.html")}
    )
    result = server.get_tournament("6ad412a", ratings_at_event=True)
    row = next(r for r in result["standings"] if r["player_id"] == "1c18ed8")
    assert row["rating_current"] == pytest.approx(84.48)
    assert row["rating_at_event"] == pytest.approx(90.00)
    assert result["ratings_at_event_resolved"] == 1
    assert len(result["ratings_at_event_missing"]) == 16
    assert "1c18ed8" not in result["ratings_at_event_missing"]
    assert len(client.calls) == 18  # турнир плюс семнадцать профилей


def test_ratings_at_event_is_off_by_default(stub, load_fixture):
    client = stub(load_fixture("tournament.html"))
    result = server.get_tournament("6ad412a")
    assert len(client.calls) == 1
    assert "rating_at_event" not in result["standings"][0]
    assert result["ratings_at_event_resolved"] is None


def test_ratings_at_event_all_profiles_unavailable(stub_multi, load_fixture):
    # Сайт лежит или отдаёт ошибки на все семнадцать профилей. Таблица
    # обязана вернуться целиком, без падений и без выдуманных значений.
    client = stub_multi({"6ad412a": load_fixture("tournament.html")})
    result = server.get_tournament("6ad412a", ratings_at_event=True)
    assert len(result["standings"]) == 17
    assert all(row["rating_at_event"] is None for row in result["standings"])
    assert result["ratings_at_event_resolved"] == 0
    ids = [row["player_id"] for row in result["standings"]]
    assert sorted(result["ratings_at_event_missing"]) == sorted(ids)
    assert len(client.calls) == 18  # турнир плюс семнадцать неудачных попыток


def test_ratings_at_event_on_tournament_without_standings(stub_multi, load_fixture):
    # Турнир до подведения итогов: строк в таблице ещё нет. Разрешать
    # нечего, поэтому profiles не запрашиваются вовсе, а resolved — 0,
    # а не null (флаг включён).
    html = load_fixture("tournament.html")
    stripped = re.sub(r'<tr><td class="player-place-cell".*?</tr>', "", html, flags=re.S)
    client = stub_multi({"6ad412a": stripped})
    result = server.get_tournament("6ad412a", ratings_at_event=True)
    assert result["standings"] == []
    assert result["ratings_at_event_resolved"] == 0
    assert result["ratings_at_event_missing"] == []
    assert len(client.calls) == 1  # только страница турнира, ни одного профиля


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
    assert "не ограничена фиксированным окном" in doc
    assert "rated_periods" in doc
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


def test_get_player_can_skip_matches(stub, load_fixture):
    stub(load_fixture("player_veteran.html"))
    result = server.get_player("66f1645", include_matches=False)
    assert "matches" not in result
    assert result["matches_total"] == 106


def test_get_player_rejects_non_iso_since(stub):
    client = stub()
    with pytest.raises(ToolError, match="matches_since"):
        server.get_player("66f1645", matches_since="13.09.2026")
    assert client.calls == []


def test_tournament_matches_are_collected_from_participants(stub_multi, load_fixture):
    # Страница турнира матчей не содержит — они лежат в профилях участников.
    stub_multi(
        {
            "6ad412a": load_fixture("tournament.html"),
            "1c18ed8": load_fixture("player_novice.html"),
            "17828c3": load_fixture("player_participant.html"),
        }
    )
    result = server.get_tournament_matches("6ad412a")
    assert result["date"] == "2026-09-13"
    assert result["participants"] == 17
    assert all(m["date"] == "2026-09-13" for m in result["matches"])
    # Девять матчей у каждого из двух собранных профилей, один общий.
    assert len(result["matches"]) == 17
    assert len(result["missing_profiles"]) == 15
    shared = [
        m
        for m in result["matches"]
        if {m["player_id"], m["opponent_id"]} == {"1c18ed8", "17828c3"}
    ]
    assert len(shared) == 1, "общий матч отдаётся один раз, а не дважды"


def test_mirror_mismatch_is_loud(stub_multi, load_fixture):
    # Один матч виден с двух сторон. Если счета не зеркальны, выбирать
    # версию молча нельзя: это изменившаяся вёрстка или ошибка разбора.
    broken = load_fixture("player_participant.html").replace(
        '<td class="game-score-cell">2:1</td>'
        '<td class="game-name-cell"><a href="/players/?id=1c18ed8">',
        '<td class="game-score-cell">2:0</td>'
        '<td class="game-name-cell"><a href="/players/?id=1c18ed8">',
        1,
    )
    assert broken != load_fixture("player_participant.html"), "замена обязана сработать"
    stub_multi(
        {
            "6ad412a": load_fixture("tournament.html"),
            "1c18ed8": load_fixture("player_novice.html"),
            "17828c3": broken,
        }
    )
    with pytest.raises(ToolError, match="ParseError"):
        server.get_tournament_matches("6ad412a")
