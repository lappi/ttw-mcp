"""MCP-сервер над r.ttw.ru.

Докстринги инструментов — интерфейс для языковой модели. В них описаны
ограничения источника, без знания которых модель делает неверные выводы.
"""

import functools
import re

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ttw_mcp.client import TtwClient
from ttw_mcp.errors import InvalidInput, TtwError
from ttw_mcp.parsers.head_to_head import parse_head_to_head
from ttw_mcp.parsers.player import parse_player_profile
from ttw_mcp.parsers.search import parse_player_search, parse_tournament_search
from ttw_mcp.parsers.tournament import parse_tournament

mcp = MCPServer("ttw")
_client = TtwClient()

# fullmatch без якорей, а не match с "$": в Python "$" совпадает и перед
# завершающим переводом строки, так что "1c18ed8\n" прошёл бы проверку и
# ушёл бы в запрос, нарушая правило «отказ до обращения к сети».
_ID = re.compile(r"[0-9a-f]{4,16}")
_DATE = re.compile(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}")


def _reporting(fn):
    """Доносит ошибки проекта до модели.

    SDK превращает всё, кроме ToolError, в безликое "Error executing tool
    <name>", и тогда ParseError теряет имя селектора, а NotFound становится
    неотличим от падения сайта. Перевод делаем здесь: errors.py и parsers/
    остаются свободны от зависимости на MCP.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except TtwError as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    return wrapper


def _valid_id(value: str, field: str) -> str:
    if not _ID.fullmatch(value or ""):
        raise InvalidInput(f"{field} должен быть hex-строкой вида 1c18ed8, получено {value!r}")
    return value


def _valid_name(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise InvalidInput(f"{field} не может быть пустым")
    return cleaned


@mcp.tool()
@_reporting
def search_players(name: str, limit: int = 25) -> dict:
    """Ищет игроков по фамилии или части имени.

    Имя обязательно: без него сайт отдаёт весь список на 6.7 МБ.
    Сайт возвращает максимум 500 строк без пагинации; при достижении
    потолка поле truncated равно true и запрос надо сузить.
    Однофамильцев много, различать их следует по городу и рейтингу.

    Аргумент limit укорачивает только список players. Поле total_found
    всегда показывает, сколько строк реально нашлось на странице, поэтому
    эти два числа расходятся намеренно, а не по ошибке.
    """
    cleaned = _valid_name(name, "name")
    html = _client.get_html("/players/", {"player-name": cleaned})
    return parse_player_search(html, limit=limit)


@mcp.tool()
@_reporting
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

    Неопознанный счёт приходит с result "unparsed" — это признак изменившейся
    вёрстки, а не результат матча.
    """
    html = _client.get_html("/players/", {"id": _valid_id(player_id, "player_id")})
    return parse_player_profile(html, player_id)


@mcp.tool()
@_reporting
def get_head_to_head(player_id: str, opponent_id: str) -> dict:
    """Возвращает очное противостояние двух игроков.

    Даёт победы, проценты побед и партий, текущие рейтинги обоих и список
    всех их встреч. Рейтинги на этой странице округлены до целого; за
    точным значением с двумя знаками идите в get_player.

    Пустой matches означает, что игроки не встречались.

    Матч без разборчивого счёта — техническая победа или изменившаяся
    вёрстка — приходит с пустыми партиями и исходной записью в score_raw.
    В отличие от get_player, здесь нет поля result, поэтому различить эти
    два случая можно только по score_raw.
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
@_reporting
def search_tournaments(name: str = "", date: str = "") -> dict:
    """Ищет турниры по названию и дате.

    Нужен хотя бы один аргумент. Дата задаётся в формате сайта DD.MM.YYYY,
    а не в ISO — это единственное место в проекте, где наружу смотрит формат
    источника, потому что значение уходит в его же поисковую форму.

    Сайт отдаёт максимум 20 результатов без пагинации; при достижении
    потолка truncated равно true.
    """
    if not (name or "").strip() and not (date or "").strip():
        raise InvalidInput("нужен хотя бы один из аргументов: name или date")
    if date.strip() and not _DATE.fullmatch(date.strip()):
        raise InvalidInput(f"date должен быть в формате DD.MM.YYYY, получено {date!r}")
    html = _client.post_ajax("get_tournaments_by_name", name=name, date=date)
    return parse_tournament_search(html)


@mcp.tool()
@_reporting
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
