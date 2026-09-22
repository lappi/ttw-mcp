"""MCP-сервер над r.ttw.ru.

Докстринги инструментов — интерфейс для языковой модели. В них описаны
ограничения источника, без знания которых модель делает неверные выводы.
"""

import re

from mcp.server.mcpserver import MCPServer

from ttw_mcp.client import TtwClient
from ttw_mcp.errors import InvalidInput
from ttw_mcp.parsers.head_to_head import parse_head_to_head
from ttw_mcp.parsers.player import parse_player_profile
from ttw_mcp.parsers.search import parse_player_search, parse_tournament_search
from ttw_mcp.parsers.tournament import parse_tournament

mcp = MCPServer("ttw")
_client = TtwClient()

_ID = re.compile(r"^[0-9a-f]{4,16}$")


def _valid_id(value: str, field: str) -> str:
    if not _ID.match(value or ""):
        raise InvalidInput(f"{field} должен быть hex-строкой вида 1c18ed8, получено {value!r}")
    return value


def _valid_name(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise InvalidInput(f"{field} не может быть пустым")
    return cleaned


@mcp.tool()
def search_players(name: str, limit: int = 25) -> dict:
    """Ищет игроков по фамилии или части имени.

    Имя обязательно: без него сайт отдаёт весь список на 6.7 МБ.
    Сайт возвращает максимум 500 строк без пагинации; при достижении
    потолка поле truncated равно true и запрос надо сузить.
    Однофамильцев много, различать их следует по городу и рейтингу.
    """
    cleaned = _valid_name(name, "name")
    html = _client.get_html("/players/", {"player-name": cleaned})
    return parse_player_search(html, limit=limit)


@mcp.tool()
def get_player(player_id: str) -> dict:
    """Возвращает профиль игрока: сводку, периоды рейтинга, турниры и все матчи.

    Данные охватывают последние 12 месяцев — более глубокой истории сайт
    не хранит ни в одном источнике.

    Важно: блок summary отстаёт на один недельный период и не включает
    самый свежий турнир, тогда как matches его включает. Расхождение
    между summary["games"] и длиной matches — нормальное поведение
    источника, а не ошибка. Для подсчётов используйте matches.

    Пустой best_wins означает отсутствие заметных побед, а не сбой.

    Техническая победа приходит с result "walkover", score_for и
    score_against равны null, а исходная запись сайта лежит в score_raw.
    Такой матч сыгран и учитывается наравне с остальными.
    """
    html = _client.get_html("/players/", {"id": _valid_id(player_id, "player_id")})
    return parse_player_profile(html, player_id)


@mcp.tool()
def get_head_to_head(player_id: str, opponent_id: str) -> dict:
    """Возвращает очное противостояние двух игроков.

    Даёт победы, проценты побед и партий, текущие рейтинги обоих и список
    всех их встреч. Рейтинги на этой странице округлены до целого; за
    точным значением с двумя знаками идите в get_player.

    Пустой matches означает, что игроки не встречались.
    """
    return parse_head_to_head(
        _client.get_html(
            "/players/",
            {
                "id": _valid_id(player_id, "player_id"),
                "with": _valid_id(opponent_id, "opponent_id"),
            },
        ),
        player_id,
        opponent_id,
    )


@mcp.tool()
def search_tournaments(name: str = "", date: str = "") -> dict:
    """Ищет турниры по названию и дате.

    Нужен хотя бы один аргумент. Сайт отдаёт максимум 20 результатов без
    пагинации; при достижении потолка truncated равно true.
    """
    if not (name or "").strip() and not (date or "").strip():
        raise InvalidInput("нужен хотя бы один из аргументов: name или date")
    html = _client.post_ajax("get_tournaments_by_name", name=name, date=date)
    return parse_tournament_search(html)


@mcp.tool()
def get_tournament(tournament_id: str) -> dict:
    """Возвращает турнир: метаданные, итоговую таблицу и другие турниры серии.

    Страница содержит только итоговую таблицу. Отдельных матчей турнира на
    ней нет — чтобы узнать, кто с кем играл, нужны профили участников
    через get_player.
    """
    html = _client.get_html(
        "/tournaments/", {"id": _valid_id(tournament_id, "tournament_id")}
    )
    return parse_tournament(html, tournament_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
