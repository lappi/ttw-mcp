"""Обновление тестовых фикстур с живого сайта.

Запускается вручную, когда надо проверить, не изменилась ли вёрстка:

    uv run python scripts/fetch_fixtures.py

Большой файл поиска сохраняется сжатым: 485 КБ несжатого HTML в репозитории
ни к чему, а conftest читает .gz прозрачно.
"""

import gzip
import time
from pathlib import Path

import httpx

from ttw_mcp.client import TtwClient

BASE = "https://r.ttw.ru"
UA = TtwClient.USER_AGENT
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

PAGES = [
    ("player_novice.html", "GET", "/players/", {"id": "1c18ed8"}),
    ("player_veteran.html", "GET", "/players/", {"id": "66f1645"}),
    ("player_not_found.html", "GET", "/players/", {"id": "deadbee"}),
    ("head_to_head.html", "GET", "/players/", {"id": "1c18ed8", "with": "17828c3"}),
    ("head_to_head_walkover.html", "GET", "/players/", {"id": "66f1645", "with": "730eb6d"}),
    ("tournament.html", "GET", "/tournaments/", {"id": "6ad412a"}),
    ("search_players_many.html", "GET", "/players/", {"player-name": "фомин"}),
    ("search_players_capped.html.gz", "GET", "/players/", {"player-name": "иванов"}),
    (
        "search_tournaments.html",
        "POST",
        "/wp-admin/admin-ajax.php",
        {"action": "get_tournaments_by_name", "name": "энерджи", "date": ""},
    ),
    ("head_to_head_never_met.html", "GET", "/players/", {"id": "1c18ed8", "with": "7063200"}),
    ("search_players_zero.html", "GET", "/players/", {"player-name": "яяяяяя"}),
    ("player_walkover_loss.html.gz", "GET", "/players/", {"id": "44d227e"}),
    ("player_walkover_tech.html.gz", "GET", "/players/", {"id": "23a3d0d"}),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=BASE, headers={"User-Agent": UA}, timeout=60.0) as client:
        for name, method, path, params in PAGES:
            if method == "GET":
                response = client.get(path, params=params)
            else:
                response = client.post(path, data=params)
            response.raise_for_status()
            target = OUT / name
            if name.endswith(".gz"):
                target.write_bytes(gzip.compress(response.text.encode("utf-8")))
            else:
                target.write_text(response.text, encoding="utf-8")
            print(f"{name}: {len(response.text)} символов")
            time.sleep(2)


if __name__ == "__main__":
    main()
