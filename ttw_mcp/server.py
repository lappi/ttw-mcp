"""MCP-сервер над r.ttw.ru.

Докстринги инструментов — интерфейс для языковой модели. В них описаны
ограничения источника, без знания которых модель делает неверные выводы.
"""

import functools
import re

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ttw_mcp.client import TtwClient
from ttw_mcp.collect import collect_profiles
from ttw_mcp.errors import InvalidInput, ParseError, TtwError
from ttw_mcp.parsers.head_to_head import parse_head_to_head
from ttw_mcp.parsers.player import parse_player_profile
from ttw_mcp.parsers.search import parse_player_search, parse_tournament_search
from ttw_mcp.parsers.tournament import parse_tournament
from ttw_mcp.rating import annotate_matches, rating_at_event

mcp = MCPServer("ttw")
_client = TtwClient()

# fullmatch без якорей, а не match с "$": в Python "$" совпадает и перед
# завершающим переводом строки, так что "1c18ed8\n" прошёл бы проверку и
# ушёл бы в запрос, нарушая правило «отказ до обращения к сети».
_ID = re.compile(r"[0-9a-f]{4,16}")
_DATE = re.compile(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


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
def get_player(
    player_id: str, include_matches: bool = True, matches_since: str = ""
) -> dict:
    """Возвращает профиль игрока: сводку, периоды рейтинга, турниры и все матчи.

    История не ограничена фиксированным окном: страница отдаёт все недельные
    периоды, в которых игрока обсчитывали. Замерено от 19 до 94 периодов у
    разных игроков, самый ранний — октябрь 2023 года. Глубина отражает
    активность самого игрока, а не срок хранения на сайте, поэтому
    многолетние вопросы к этим данным правомерны.

    Осторожно с summary["rated_periods"]: оно упирается в 30. У игрока с 94
    периодами сводка покажет 30, то есть занизит. Считать периоды следует
    по длине periods, а не по этому полю.

    Важно: блок summary отстаёт на один недельный период и не включает
    самый свежий турнир, тогда как matches его включает. Расхождение
    между summary["games"] и длиной matches — нормальное поведение
    источника, а не ошибка. Для подсчётов используйте matches.

    Пустой best_wins означает отсутствие заметных побед, а не сбой.

    Каждая запись matches и best_wins несёт player_rating_at_match —
    восстановленный рейтинг самого игрока непосредственно перед этим
    событием. Сайт даёт рейтинг соперника, но не собственный, и без этого
    поля матч нельзя сопоставить по силе сторон. Значение может быть null
    по двум независимым причинам: дата вне периодов, покрытых таблицей
    рейтинга (история усечена), либо у игрока в этот день два турнира и
    сайт не сообщает их порядок. В обоих случаях это честный отказ — не
    подставляйте вместо null приближение. В best_wins отдельно есть
    player_rating_current — сегодняшний рейтинг игрока (не на момент
    победы!), который показывает сайт; для сопоставления по силе сторон
    нужен именно player_rating_at_match.

    Технический результат приходит с result "walkover_win" или "walkover_loss",
    score_for и score_against равны null, а исходная запись сайта лежит в
    score_raw. Такой матч сыгран и учитывается наравне с остальными.

    Несыгранный матч помечается result "not_played" и не учитывается ни как
    победа, ни как поражение; score_for и score_against равны null.

    Неопознанный счёт приходит с result "unparsed" — это признак изменившейся
    вёрстки, а не результат матча.

    Список matches — основной объём ответа. Если он не нужен, ставьте
    include_matches=False: тогда ключи matches и best_wins в ответе
    отсутствуют (а не пусты), но matches_total и best_wins_total
    присутствуют всегда и считаются по полному списку. matches_since
    (формат YYYY-MM-DD) сужает matches до матчей не раньше этой даты, не
    трогая при этом matches_total — оно по-прежнему про весь список. При
    include_matches=False значение matches_since молча игнорируется:
    фильтровать нечего, ошибки это не вызывает.
    """
    since = matches_since.strip() or None
    if since is not None and not _ISO_DATE.fullmatch(since):
        raise InvalidInput(
            f"matches_since должен быть в формате YYYY-MM-DD, получено {matches_since!r}"
        )
    html = _client.get_html("/players/", {"id": _valid_id(player_id, "player_id")})
    profile = parse_player_profile(
        html, player_id, include_matches=include_matches, matches_since=since
    )
    if include_matches:
        annotate_matches(profile)
    return profile


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
def get_tournament(tournament_id: str, ratings_at_event: bool = False) -> dict:
    """Возвращает турнир: метаданные, итоговую таблицу и другие турниры серии.

    Страница содержит только итоговую таблицу. Отдельных матчей турнира на
    ней нет — чтобы узнать, кто с кем играл, нужны профили участников
    через get_player.

    У каждой строки standings есть rating_current — это сегодняшний
    рейтинг игрока, тот, что прямо сейчас показывает сайт, а не тот, с
    которым он выходил играть этот турнир. Разница доходит до сотен
    пунктов, и по этому полю нельзя судить о силе поля на дату турнира.

    Флаг ratings_at_event=True восстанавливает исторический рейтинг:
    добавляет каждой строке standings поле rating_at_event — рейтинг
    игрока непосредственно перед турниром. Значение может быть null:
    профиль игрока недоступен, дата вне периодов, покрытых историей
    рейтинга, либо в этот день у игрока было два турнира и порядок между
    ними сайт не сообщает. Это честный отказ, а не ошибка разбора.

    Цена флага высокая: восстановление требует отдельного запроса профиля
    на каждого участника, и запросы идут строго последовательно — сайт
    закрыт для параллельных обращений и отвечает 4–17 секунд на запрос.
    На турнире из семнадцати участников это восемнадцать запросов подряд
    (профили плюс сама страница турнира), то есть от минуты до пяти на
    крупном турнире. Без необходимости в rating_at_event флаг лучше не
    включать.

    ratings_at_event_resolved — сколько строк standings получили
    rating_at_event; null, когда флаг выключен. ratings_at_event_missing —
    идентификаторы игроков, чьи профили получить не удалось; этого ключа
    нет в ответе, если флаг выключен.
    """
    html = _client.get_html(
        "/tournaments/", {"id": _valid_id(tournament_id, "tournament_id")}
    )
    result = parse_tournament(html, tournament_id)

    if not ratings_at_event:
        result["ratings_at_event_resolved"] = None
        return result

    ids = [row["player_id"] for row in result["standings"]]
    profiles, missing = collect_profiles(_client, ids, include_matches=False)
    resolved = 0
    for row in result["standings"]:
        profile = profiles.get(row["player_id"])
        value = rating_at_event(profile, result["date"]) if profile else None
        row["rating_at_event"] = value
        resolved += value is not None
    result["ratings_at_event_resolved"] = resolved
    result["ratings_at_event_missing"] = missing
    return result


_MIRROR = {
    "win": "loss",
    "loss": "win",
    "walkover_win": "walkover_loss",
    "walkover_loss": "walkover_win",
    "not_played": "not_played",
    "unparsed": "unparsed",
}


def _is_mirror(left: dict, right: dict) -> bool:
    """Две записи описывают один и тот же матч с разных сторон."""
    return (
        left["score_for"] == right["score_against"]
        and left["score_against"] == right["score_for"]
        and _MIRROR.get(left["result"]) == right["result"]
    )


def _reconcile_matches(profiles: dict[str, dict], tournament_id: str) -> list[dict]:
    """Сводит матчи одного турнира из профилей участников.

    Отбор идёт по tournament_id, а не по дате: участник мог в тот же день
    сыграть ещё один турнир (get_tournament это отдельно оговаривает), и
    фильтр по дате затянул бы в выдачу матчи чужого турнира того же дня —
    в лучшем случае лишние строки, в худшем ParseError на исправных
    данных, если у такой строки случайно не нашлось бы зеркала. Замерено,
    что поле tournament_id заполнено у всех проверенных матчей и в дни с
    двумя турнирами делит их начисто.

    Матч виден с двух сторон, если собраны оба профиля, и с одной, если
    собран только один. Строки группируются по паре игроков, и каждой
    ищется зеркальная у соперника. Пары играют дважды за день постоянно —
    групповой этап плюс плей-офф, — поэтому сводятся списки с учётом
    кратности, а не одиночные записи.

    Если у строки нет зеркала, а профиль соперника собран, поднимается
    ParseError: выбрать одну из двух версий счёта молча значило бы отдать
    модели выдуманный результат.
    """
    rows: dict[tuple[str, str], list[dict]] = {}
    for player_id, profile in profiles.items():
        for match in profile.get("matches", []):
            if match["tournament_id"] != tournament_id:
                continue
            key = tuple(sorted((player_id, match["opponent_id"])))
            rows.setdefault(key, []).append(
                {
                    "player_id": player_id,
                    "opponent_id": match["opponent_id"],
                    "date": match["date"],
                    "score_raw": match["score_raw"],
                    "score_for": match["score_for"],
                    "score_against": match["score_against"],
                    "result": match["result"],
                    "delta": match["delta"],
                }
            )

    matches: list[dict] = []
    for (left_id, right_id), entries in rows.items():
        left = [e for e in entries if e["player_id"] == left_id]
        spare = [e for e in entries if e["player_id"] == right_id]
        for entry in left:
            mirror = next((o for o in spare if _is_mirror(entry, o)), None)
            if mirror is not None:
                spare.remove(mirror)
            elif right_id in profiles:
                raise ParseError(
                    "get_tournament_matches",
                    "game-score-cell",
                    f"нет зеркальной записи в профиле {right_id}: {entry}",
                )
            matches.append(entry)
        for leftover in spare:
            if left_id in profiles:
                raise ParseError(
                    "get_tournament_matches",
                    "game-score-cell",
                    f"нет зеркальной записи в профиле {left_id}: {leftover}",
                )
            matches.append(leftover)

    matches.sort(key=lambda m: (m["player_id"], m["opponent_id"], m["score_raw"]))
    return matches


@mcp.tool()
@_reporting
def get_tournament_matches(tournament_id: str) -> dict:
    """Матчи, сыгранные на турнире.

    Страница турнира их не содержит — они есть только в профилях
    участников, поэтому инструмент загружает профиль каждого: запросов
    столько же, сколько участников, идут строго последовательно, и уже
    для семнадцати участников это минуты.

    Каждый матч присутствует в профилях обоих игроков и отдаётся один раз;
    если пара встретилась дважды за день — групповой этап и плей-офф это
    постоянно, — в выдаче будут обе встречи, а не одна. score_for,
    score_against, delta и result в записи — со стороны того игрока, чей
    идентификатор стоит в player_id, а не соперника и не усреднены.

    Расхождение счетов между двумя сторонами поднимает ParseError: выбрать
    версию молча значило бы отдать модели выдуманный результат.

    missing_profiles перечисляет участников, чей профиль получить не
    удалось; их матчи в выдачу не попали.
    """
    html = _client.get_html(
        "/tournaments/", {"id": _valid_id(tournament_id, "tournament_id")}
    )
    tournament = parse_tournament(html, tournament_id)
    date = tournament["date"]
    ids = [row["player_id"] for row in tournament["standings"]]
    profiles, missing = collect_profiles(_client, ids)
    matches = _reconcile_matches(profiles, tournament_id)

    return {
        "tournament_id": tournament_id,
        "title": tournament["title"],
        "date": date,
        "participants": tournament["participants_count"],
        "matches": matches,
        "missing_profiles": missing,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
