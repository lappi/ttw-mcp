"""Тесты сборщика профилей `ttw_mcp.collect.collect_profiles`."""

import pytest

from ttw_mcp.collect import collect_profiles
from ttw_mcp.errors import ParseError, UpstreamError


class RecordingClient:
    """Отдаёт заранее подготовленный HTML и считает обращения."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def get_html(self, path, params):
        self.calls.append(params["id"])
        if params["id"] not in self.pages:
            raise UpstreamError(f"/players/?id={params['id']}", "HTTP 500")
        return self.pages[params["id"]]


def test_every_identifier_is_fetched_once(load_fixture):
    client = RecordingClient({"1c18ed8": load_fixture("player_novice.html")})
    profiles, missing = collect_profiles(client, ["1c18ed8", "1c18ed8", "1c18ed8"])
    assert client.calls == ["1c18ed8"]
    assert list(profiles) == ["1c18ed8"]
    assert missing == []


def test_a_failed_profile_does_not_cancel_the_rest(load_fixture):
    # Один недоступный игрок не должен обнулять состав из восемнадцати.
    client = RecordingClient({"1c18ed8": load_fixture("player_novice.html")})
    profiles, missing = collect_profiles(client, ["1c18ed8", "deadbee"])
    assert list(profiles) == ["1c18ed8"]
    assert missing == ["deadbee"]


def test_requests_go_in_the_given_order(load_fixture):
    pages = {
        "1c18ed8": load_fixture("player_novice.html"),
        "66f1645": load_fixture("player_veteran.html"),
    }
    client = RecordingClient(pages)
    collect_profiles(client, ["66f1645", "1c18ed8"])
    assert client.calls == ["66f1645", "1c18ed8"]


def test_include_matches_false_is_passed_through(load_fixture):
    client = RecordingClient({"66f1645": load_fixture("player_veteran.html")})
    profiles, _ = collect_profiles(client, ["66f1645"], include_matches=False)
    assert "matches" not in profiles["66f1645"]
    assert profiles["66f1645"]["matches_total"] == 106


def test_a_broken_page_is_not_reported_as_a_missing_player(load_fixture):
    # Сломанный разбор — это наша поломка, и она системная: при смене
    # вёрстки так ляжет каждый профиль. Молча выдать «игроков не нашлось»
    # значит соврать модели.
    client = RecordingClient({"1c18ed8": "<html><body>ничего похожего</body></html>"})
    with pytest.raises(ParseError):
        collect_profiles(client, ["1c18ed8"])
