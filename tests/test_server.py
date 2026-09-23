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
                self.ajax = ""

            def get_html(self, path, params):
                key = params["id"]
                self.calls.append(key)
                if key not in pages:
                    raise NotFound(f"нет страницы для {key}")
                return pages[key]

            def post_ajax(self, action, **fields):
                self.calls.append(f"{action}:{fields.get('date', '')}")
                return self.ajax

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


def test_docstrings_carry_the_measured_gotchas():
    # Докстринг — единственный канал, из которого модель узнаёт об
    # ограничениях источника. Подстрочные проверки тут бесполезны, поэтому
    # сверяемся с формулировками, которые нельзя удовлетворить текстом
    # противоположного смысла. Слабость этих проверок известна: они ловят
    # молчание докстринга о поле, а не враньё в его тексте.
    player = server.get_player.__doc__
    assert "rated_periods" in player and "не несёт информации" in player
    assert "walkover_win" in player and "walkover_loss" in player
    assert "not_played" in player
    assert "seed_rating" in player and "first_rated_date" in player
    assert "matches_total" in player
    assert "rating_min" in player
    assert "player_rating_current" in player
    assert "hand" in player

    tournament = server.get_tournament.__doc__
    assert "rating_current" in tournament
    assert "rating_at_event" in tournament
    assert "сумма дельт" in tournament
    assert "ratings_at_event_resolved" in tournament

    matches = server.get_tournament_matches.__doc__
    assert "player_id" in matches

    series = server.get_series.__doc__
    assert "включая запрошенный" in series

    search_t = server.search_tournaments.__doc__
    assert "total_found" in search_t

    search = server.search_players.__doc__
    assert "город" in search and "ненадёжно" in search
    assert "несколько профилей" in search


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


def test_impossible_matches_since_is_refused(stub, load_fixture):
    # _ISO_DATE.fullmatch проверяет только форму ГГГГ-ММ-ДД; 2026-13-01 её
    # проходит. Без разбора по-настоящему фильтрация пошла бы строковым
    # сравнением и молча вернула бы matches: [] — неотличимо от «матчей
    # после этой даты нет».
    client = stub(load_fixture("player_veteran.html"))
    with pytest.raises(ToolError, match="не является датой"):
        server.get_player("66f1645", matches_since="2026-13-01")
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
    assert result["participants_count"] == 17
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


def test_series_merges_page_and_participants(stub_multi, load_fixture):
    stub_multi(
        {
            "6ad412a": load_fixture("tournament.html"),
            "1c18ed8": load_fixture("player_novice.html"),
            "17828c3": load_fixture("player_participant.html"),
        }
    )
    result = server.get_series("6ad412a", limit=10)
    assert result["title"] == "Санкт Петербург. Турнир Энерджи Арена."
    assert result["events_found"] == 9
    assert [e["id"] for e in result["events"]] == [
        "5f73688",
        "6ad412a",
        "6705776",
        "6406361",
        "423f3e9",
        "7de1a9d",
        "79a8c89",
        "5f86873",
        "6a98dbd",
    ]
    assert len(result["missing_profiles"]) == 15


def test_series_recovers_events_the_site_list_omits(stub_multi, load_fixture):
    # Список на странице кончается июлем, а сентябрьские турниры серии
    # лежат только в профилях участников — и написаны иначе: без точки в
    # конце и с пробелом перед ней. Точное сравнение названий потеряло бы
    # именно свежие турниры, ради которых инструмент и нужен.
    stub_multi(
        {
            "6ad412a": load_fixture("tournament.html"),
            "1c18ed8": load_fixture("player_novice.html"),
            "17828c3": load_fixture("player_participant.html"),
        }
    )
    result = server.get_series("6ad412a")
    from_profiles = {e["id"] for e in result["events"] if e["source"] == "participants"}
    assert from_profiles == {"5f73688", "6ad412a", "6705776", "6406361"}
    newest = result["events"][0]
    assert newest["id"] == "5f73688" and newest["source"] == "participants"


def test_series_events_have_one_shape(stub_multi, load_fixture):
    # У записи из профиля нет адреса и числа участников, но ключи есть и
    # равны null: иначе модель не отличит «поля нет» от «значение пустое».
    stub_multi(
        {
            "6ad412a": load_fixture("tournament.html"),
            "1c18ed8": load_fixture("player_novice.html"),
        }
    )
    result = server.get_series("6ad412a")
    shapes = {tuple(sorted(e)) for e in result["events"]}
    assert len(shapes) == 1
    from_page = next(e for e in result["events"] if e["source"] == "page")
    from_profile = next(e for e in result["events"] if e["source"] == "participants")
    assert from_page["participants"] is not None
    assert from_profile["participants"] is None


def test_series_limit_truncates_but_reports_the_whole(stub_multi, load_fixture):
    stub_multi(
        {
            "6ad412a": load_fixture("tournament.html"),
            "1c18ed8": load_fixture("player_novice.html"),
            "17828c3": load_fixture("player_participant.html"),
        }
    )
    result = server.get_series("6ad412a", limit=3)
    assert len(result["events"]) == 3
    assert result["events_found"] == 9


def test_series_rejects_a_non_positive_limit(stub, load_fixture):
    client = stub(load_fixture("tournament.html"))
    with pytest.raises(ToolError, match="limit"):
        server.get_series("6ad412a", limit=0)
    assert client.calls == []


def test_series_comes_entirely_from_participants_when_page_list_is_empty(
    stub_multi, load_fixture
):
    # У первого турнира серии список на странице пуст — не отсутствует,
    # а пуст: ни одной строки серии, только строка самого турнира. Получаем
    # такую фикстуру тем же приёмом, что и для турнира без итоговой
    # таблицы: вырезаем регулярным выражением лишние строки, оставляя
    # первую (иначе она перестанет описывать запрошенный турнир и
    # parse_tournament упадёт на сверке own["id"] с tournament_id).
    html = load_fixture("tournament.html")
    seen = 0

    def _keep_first(match: re.Match) -> str:
        nonlocal seen
        seen += 1
        return match.group(0) if seen == 1 else ""

    stripped = re.sub(
        r'<tr><td class="tournament-date-cell".*?</tr>', _keep_first, html, flags=re.S
    )
    stub_multi(
        {
            "6ad412a": stripped,
            "1c18ed8": load_fixture("player_novice.html"),
            "17828c3": load_fixture("player_participant.html"),
        }
    )
    result = server.get_series("6ad412a")
    assert result["events"], "серия не пуста"
    assert all(e["source"] == "participants" for e in result["events"])
    assert result["events_found"] == len(result["events"])


def test_series_falls_back_to_page_list_when_no_profile_is_reachable(stub_multi, load_fixture):
    # Сайт лежит целиком: ни один профиль не собрать. Серия тогда честно
    # собирается только из списка на странице, а не превращается в пустоту
    # или падение.
    stub_multi({"6ad412a": load_fixture("tournament.html")})
    result = server.get_series("6ad412a")
    assert len(result["events"]) == 5
    assert all(e["source"] == "page" for e in result["events"])
    assert len(result["missing_profiles"]) == 17


@pytest.mark.parametrize(
    "left,right",
    [
        ("Город. Турнир Имени Кого-то.", "Город. Турнир Имени Кого-то"),
        ("Город . Турнир Имени Кого-то", "Город. Турнир Имени Кого-то"),
        ("Город.  Турнир  Имени Кого-то ", "Город. Турнир Имени Кого-то"),
        ("ГОРОД. Турнир Имени Кого-то", "город. турнир имени кого-то"),
    ],
)
def test_series_key_unifies_the_measured_spellings(left, right):
    assert server._series_key(left) == server._series_key(right)


def test_series_key_keeps_different_series_apart():
    assert server._series_key("Город. Турнир А") != server._series_key("Город. Турнир Б")


def test_date_range_queries_every_day_in_it(stub, load_fixture):
    client = stub(load_fixture("search_tournaments.html"))
    result = server.search_tournaments(date_from="01.09.2026", date_to="03.09.2026")
    # Ajax принимает одну дату, поэтому диапазон стоит по запросу на день.
    assert [call[2]["date"] for call in client.calls] == [
        "01.09.2026",
        "02.09.2026",
        "03.09.2026",
    ]
    # Заглушка отдаёт одну и ту же страницу трижды: склейка по id оставляет 20.
    assert result["total_found"] == 20
    assert result["truncated"] is True


def test_range_longer_than_two_weeks_is_refused(stub):
    client = stub()
    with pytest.raises(ToolError, match="14"):
        server.search_tournaments(date_from="01.01.2026", date_to="01.03.2026")
    assert client.calls == []


def test_range_ends_before_it_starts(stub):
    client = stub()
    with pytest.raises(ToolError, match="раньше"):
        server.search_tournaments(date_from="03.09.2026", date_to="01.09.2026")
    assert client.calls == []


def test_range_needs_both_ends(stub):
    client = stub()
    with pytest.raises(ToolError, match="вместе"):
        server.search_tournaments(date_from="01.09.2026")
    assert client.calls == []


def test_date_and_range_together_are_refused(stub):
    # Два несовместимых намерения: молча выполнить одно значило бы
    # ответить на вопрос, которого не задавали.
    client = stub()
    with pytest.raises(ToolError, match="порознь"):
        server.search_tournaments(date="01.09.2026", date_from="01.09.2026", date_to="02.09.2026")
    assert client.calls == []


def test_impossible_date_is_named_not_erased(stub):
    # Регулярка пропускает 99.99.2026; без явной проверки модель получила
    # бы стёртое «Error executing tool» без причины. Проверяем не только
    # переклассификацию в InvalidInput, но и сам текст причины, иначе
    # регресс сообщения прошёл бы незамеченным.
    client = stub()
    with pytest.raises(ToolError, match="не является датой"):
        server.search_tournaments(date_from="99.99.2026", date_to="99.99.2026")
    assert client.calls == []


def test_impossible_single_date_is_refused_before_the_network(stub):
    # Одиночный date раньше проверялся только регуляркой формата: 31.02.2026
    # проходил её и уходил в запрос, а живой сайт на такую дату отвечает
    # пустым списком — неотличимо от «турниров в этот день не было».
    client = stub()
    with pytest.raises(ToolError, match="не является датой"):
        server.search_tournaments(date="31.02.2026")
    assert client.calls == []


def test_range_of_exactly_fourteen_days_is_accepted(stub, load_fixture):
    client = stub(load_fixture("search_tournaments.html"))
    server.search_tournaments(date_from="01.09.2026", date_to="14.09.2026")
    assert len(client.calls) == 14


def test_range_of_fifteen_days_is_refused(stub):
    client = stub()
    with pytest.raises(ToolError, match="15"):
        server.search_tournaments(date_from="01.09.2026", date_to="15.09.2026")
    assert client.calls == []


def test_enrich_costs_a_request_per_row(stub_multi, load_fixture):
    client = stub_multi({"6ad412a": load_fixture("tournament.html")})
    client.ajax = '<div>1. <a href="/tournaments/?id=6ad412a">Турнир</a></div>'
    result = server.search_tournaments(name="турнир", enrich=True)
    row = result["tournaments"][0]
    assert row["date"] == "2026-09-13"
    assert row["participants"] == 17
    assert row["address"]
    # Один ajax плюс одна загрузка турнира.
    assert client.calls == ["get_tournaments_by_name:", "6ad412a"]


def test_search_without_enrich_does_not_load_tournaments(stub_multi):
    client = stub_multi({})
    client.ajax = '<div>1. <a href="/tournaments/?id=6ad412a">Турнир</a></div>'
    result = server.search_tournaments(name="турнир")
    assert "date" not in result["tournaments"][0]
    assert client.calls == ["get_tournaments_by_name:"]


def test_range_with_enrich_within_the_cap_still_enriches(stub_multi, load_fixture):
    # Три дня отдают одну и ту же ссылку: после склейки по id остаётся одна
    # строка, это меньше потолка обогащения, и запрос проходит целиком.
    client = stub_multi({"6ad412a": load_fixture("tournament.html")})
    client.ajax = '<div>1. <a href="/tournaments/?id=6ad412a">Турнир</a></div>'
    result = server.search_tournaments(
        date_from="01.09.2026", date_to="03.09.2026", enrich=True
    )
    assert result["total_found"] == 1
    assert result["tournaments"][0]["participants"] == 17


def test_range_with_enrich_over_the_cap_is_refused(monkeypatch):
    # Два дня без пересечений по турнирам: после склейки строк больше
    # потолка обогащения (20 + 2 = 22). Обогащение обязано отклониться
    # целиком до первой загрузки турнира, а не обогатить первые двадцать.
    class RangeStub:
        def __init__(self):
            self.calls = []

        def post_ajax(self, action, **fields):
            day = fields.get("date", "")
            self.calls.append(f"{action}:{day}")
            prefix = "a" if day == "01.09.2026" else "b"
            return "".join(
                f'<div>{i}. <a href="/tournaments/?id={prefix}{i:02x}">Турнир {prefix}{i}</a></div>'
                for i in range(11)
            )

        def get_html(self, path, params):
            raise AssertionError("обогащение не должно стартовать при превышении потолка")

    client = RangeStub()
    monkeypatch.setattr(server, "_client", client)
    with pytest.raises(ToolError, match="22"):
        server.search_tournaments(date_from="01.09.2026", date_to="02.09.2026", enrich=True)
    assert client.calls == [
        "get_tournaments_by_name:01.09.2026",
        "get_tournaments_by_name:02.09.2026",
    ]
