"""Проверка, что вёрстка живого сайта всё ещё совпадает с фикстурами.

Запускать вручную: uv run pytest -m smoke -v
"""

import pytest

from ttw_mcp.client import TtwClient
from ttw_mcp.parsers.player import parse_player_profile
from ttw_mcp.parsers.search import parse_player_search
from ttw_mcp.parsers.tournament import parse_tournament

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def client():
    with TtwClient() as live:
        yield live


def test_live_player_profile_still_parses(client):
    html = client.get_html("/players/", {"id": "1c18ed8"})
    profile = parse_player_profile(html, "1c18ed8")
    assert profile["player_id"] == "1c18ed8"
    assert profile["name"]
    assert profile["matches"], "матчей нет — вероятно, изменились классы game-*"


def test_live_search_still_parses(client):
    html = client.get_html("/players/", {"player-name": "фомин"})
    result = parse_player_search(html, limit=25)
    assert result["total_found"] >= 50


def test_live_tournament_still_parses(client):
    html = client.get_html("/tournaments/", {"id": "6ad412a"})
    tournament = parse_tournament(html, "6ad412a")
    assert tournament["participants_count"] == 17
    assert len(tournament["standings"]) == 17
