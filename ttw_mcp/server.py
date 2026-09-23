"""MCP-сервер над r.ttw.ru.

Докстринги инструментов — интерфейс для языковой модели. В них описаны
ограничения источника, без знания которых модель делает неверные выводы.
"""

import functools
import re
from datetime import date, datetime, timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ttw_mcp.client import TtwClient
from ttw_mcp.collect import collect_profiles
from ttw_mcp.errors import InvalidInput, TtwError
from ttw_mcp.parsers.head_to_head import parse_head_to_head
from ttw_mcp.parsers.player import parse_player_profile
from ttw_mcp.parsers.search import parse_player_search, parse_tournament_search
from ttw_mcp.parsers.tournament import parse_tournament
from ttw_mcp.rating import annotate_matches, rating_at_event
from ttw_mcp.reconcile import reconcile_matches

mcp = MCPServer("ttw")
_client = TtwClient()

# fullmatch без якорей, а не match с "$": в Python "$" совпадает и перед
# завершающим переводом строки, так что "1c18ed8\n" прошёл бы проверку и
# ушёл бы в запрос, нарушая правило «отказ до обращения к сети».
_ID = re.compile(r"[0-9a-f]{4,16}")
_DATE = re.compile(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SERIES_SPACE = re.compile(r"\s+")
_SERIES_PUNCT = re.compile(r"\s*([.,])\s*")

MAX_RANGE_DAYS = 14
MAX_ENRICH_ROWS = 20


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


def _series_key(title: str) -> str:
    """Ключ для сличения названий турниров одной серии.

    Организаторы пишут название неединообразно: то с точкой в конце, то
    без, то с пробелом перед точкой. Замерено на трёх профилях: точное
    равенство находит один турнир серии из четырёх. Сравниваются
    названия без регистра, без лишних пробелов и без хвостовой пунктуации.

    Совпадение по названию остаётся эвристикой, и она скорее недоберёт,
    чем додумает: разные серии с почти одинаковыми названиями слить
    можно, но таких в замерах нет, а вот одна серия под тремя написаниями
    встретилась сразу.
    """
    key = _SERIES_SPACE.sub(" ", title).strip().casefold()
    return _SERIES_PUNCT.sub(r"\1", key).rstrip(".,")


def _series_event(source: str, event_id: str, date: str, page: dict | None = None) -> dict:
    return {
        "id": event_id,
        "date": date,
        "source": source,
        "address": page["address"] if page else None,
        "organizers": page["organizers"] if page else None,
        "participants": page["participants"] if page else None,
        "games": page["games"] if page else None,
    }


@mcp.tool()
@_reporting
def search_players(name: str, limit: int = 25) -> dict:
    """Ищет игроков по фамилии или части имени.

    Имя обязательно: без него сайт отдаёт весь список на 6.7 МБ.
    Сайт возвращает максимум 500 строк без пагинации; при достижении
    потолка поле truncated равно true и запрос надо сузить.

    Различать однофамильцев по городу нельзя: поле city ненадёжно.
    Встречаются значения вида "--, Санкт-Петербург" и
    "Санкт-Петербург, -Санкт-Петербург" — сайт задваивает город или
    подставляет вместо него плейсхолдер "--". Для различения однофамильцев
    используйте рейтинг и число турниров.

    Поле hand несёт пометку руки из имени на сайте: "левая", "правая" или
    null. Сайт заводит под нерабочую руку отдельный профиль с отдельным
    идентификатором, поэтому один человек может иметь несколько профилей с
    разными id, city и рейтингом — например, отдельный профиль для игры
    нерабочей рукой, где рейтинг существенно ниже. Сервер не берётся эти
    профили связывать, и в выдаче они выглядят как разные люди.

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

    Осторожно с summary["rated_periods"]: оно упирается в 30, и при значении
    30 не несёт информации о реальной длине истории — у профиля с 91
    периодом это поле покажет те же 30, что и у профиля, где периодов и
    правда 30. Ниже потолка оно честное: у профиля с 2 периодами оно равно
    3, то есть len(periods) + 1 (периоды плюс стартовая точка перед ними).
    Считать периоды следует по длине periods, а не по этому полю.

    summary["rating_min"], ["rating_max"] и ["rating_avg"] — тоже не то, чем
    кажутся: это не минимум, максимум и среднее за карьеру, а величины в
    пределах не более чем тридцатипериодного окна. На профиле с 91 периодом
    карьерный минимум по periods — 54.73, а summary["rating_min"] показывает
    249.6 — это минимум по последним тридцати периодам, а не по всем 91. На
    более короткой истории (13 периодов, все внутри окна) минимум из
    summary всё равно не совпал с минимумом среди periods[].rating_after
    этих периодов (115.0 против 122.1 в замере) — вместо этого он совпал с
    summary["seed_rating"], стартовым рейтингом до первого периода. Способ,
    которым сайт получает summary["rating_avg"], воспроизвести не удалось:
    на той же выборке в 13 периодов сайт показывает 199.84, а простое
    среднее periods[].rating_after по этим периодам — 171.85. Для точного
    минимума, максимума и среднего за карьеру считайте по periods сами, а
    не по summary.

    Важно: блок summary отстаёт на один недельный период и не включает
    самый свежий турнир, тогда как matches его включает. Расхождение
    между summary["games"] и длиной matches — нормальное поведение
    источника, а не ошибка. Для подсчётов используйте matches.

    Пустой best_wins означает отсутствие заметных побед, а не сбой.

    summary также несёт seed_rating и first_rated_date — восстановленный
    стартовый рейтинг игрока и дату его первого обсчёта: rating_after
    самого раннего периода из periods минус его delta. Оба поля равны
    null, если periods пуст, либо список доказуемо неполон — если в
    matches есть матч раньше начала самого раннего периода, сервер не
    станет выдумывать стартовый рейтинг по такой таблице.

    Поле hand в корне ответа — пометка руки самого игрока: "левая",
    "правая" или null. Поле opponent_hand в каждой записи matches и
    best_wins — то же для соперника. Сайт заводит под нерабочую руку
    отдельный профиль с отдельным идентификатором, поэтому один и тот же
    человек может стоять за двумя разными player_id с разными рейтингами;
    сервер не берётся такие профили связывать, и в ответе они выглядят
    как разные люди.

    Каждая запись matches и best_wins несёт player_rating_at_match —
    восстановленный рейтинг самого игрока непосредственно перед этим
    событием. Сайт даёт рейтинг соперника, но не собственный, и без этого
    поля матч нельзя сопоставить по силе сторон. Значение может быть null
    по двум независимым причинам: дата вне периодов, покрытых таблицей
    рейтинга (история усечена), либо у игрока в этот день два турнира и
    сайт не сообщает их порядок. В обоих случаях это честный отказ — не
    подставляйте вместо null приближение.

    Точность рейтингов различается по источникам, и смешивать их в одном
    расчёте нельзя:
    - matches[].opponent_rating — исторический рейтинг соперника на момент
      матча, с двумя знаками после запятой;
    - best_wins[].opponent_rating — тот же исторический рейтинг соперника,
      но округлённый сайтом до целого (в замерах 311.56 показано как 312,
      242.71 как 243);
    - best_wins[].player_rating_current — НЕ рейтинг на момент той победы,
      а сегодняшний рейтинг игрока, округлённый до целого; он одинаков во
      всех строках best_wins одного профиля и сравнению с соседним
      opponent_rating не подлежит — это разные временные основания. В
      одной измеренной победе opponent_rating и player_rating_current в
      строке best_wins дают разрыв 243 против 208 (35 пунктов), тогда как
      на момент того матча было 242.71 против 175.17 (67.5 пункта);
    - player_rating_at_match (и в matches, и в best_wins) —
      восстановленный рейтинг самого игрока перед турниром, с двумя
      знаками, может быть null (см. выше).

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
    if since is not None:
        if not _ISO_DATE.fullmatch(since):
            raise InvalidInput(
                f"matches_since должен быть в формате YYYY-MM-DD, получено {matches_since!r}"
            )
        # Регулярка выше проверяет только форму ГГГГ-ММ-ДД; 2026-13-01 её
        # проходит. Дальше фильтрация идёт строковым сравнением, и на такое
        # значение инструмент молча отдал бы matches: [] — неотличимо от
        # «матчей после этой даты нет». Разбираем дату по-настоящему.
        try:
            datetime.strptime(since, "%Y-%m-%d")
        except ValueError as exc:
            raise InvalidInput(
                f"matches_since: {matches_since!r} не является датой"
            ) from exc
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

    У player и opponent есть поле hand — пометка руки: "левая", "правая"
    или null. Сайт заводит под нерабочую руку отдельный профиль с отдельным
    идентификатором, так что это противостояние — только между парой
    выбранных id; если у кого-то из пары есть ещё один профиль под другой
    рукой, его встречи сюда не попадают.

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


def _day(value: str, field: str) -> date:
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError as exc:
        raise InvalidInput(f"{field}: {value!r} не является датой") from exc


def _dates_in_range(date_from: str, date_to: str) -> list[str]:
    """Перечисляет даты диапазона в формате сайта.

    Ajax принимает единственную дату, поэтому диапазон стоит по запросу на
    день. Потолок в две недели выбран как компромисс: сайт отвечает по
    4–17 секунд и просит себя не обходить, а молча выполнить перебор на год
    значило бы превратить инструмент в краулер.
    """
    start = _day(date_from, "date_from")
    end = _day(date_to, "date_to")
    if end < start:
        raise InvalidInput(f"date_to {date_to} раньше date_from {date_from}")
    days = (end - start).days + 1
    if days > MAX_RANGE_DAYS:
        raise InvalidInput(
            f"диапазон в {days} дней потребовал бы {days} запросов к сайту; "
            f"максимум {MAX_RANGE_DAYS}"
        )
    return [(start + timedelta(days=i)).strftime("%d.%m.%Y") for i in range(days)]


@mcp.tool()
@_reporting
def search_tournaments(
    name: str = "",
    date: str = "",
    date_from: str = "",
    date_to: str = "",
    enrich: bool = False,
) -> dict:
    """Ищет турниры по названию и дате.

    Нужен хотя бы один аргумент. Дата задаётся в формате сайта DD.MM.YYYY,
    а не в ISO — это единственное место в проекте, где наружу смотрит формат
    источника, потому что значение уходит в его же поисковую форму.

    date_from и date_to задают диапазон и стоят по запросу на каждый день:
    ajax принимает только одну дату. Диапазон длиннее двух недель
    отклоняется, чтобы инструмент не превратился в краулер по сайту,
    который просит себя не обходить. date и диапазон date_from/date_to
    задаются порознь: передав то и другое сразу, вы получите отказ, а не
    ответ на один из двух вопросов молча за счёт другого.

    При диапазоне строки за разные дни склеиваются по идентификатору
    турнира, поэтому total_found — это число различных турниров за весь
    диапазон, а не размер ответа за один день. truncated равно true, если
    потолок в двадцать строк был достигнут хотя бы в один из дней
    диапазона.

    enrich=True добавляет каждой строке дату, адрес и число участников,
    загружая турнир отдельно — ещё один запрос на строку. Потолок «до
    двадцати» здесь — это предел на число обогащаемых строк, а не размер
    одного ответа: при диапазоне склейка за несколько дней может собрать
    больше двадцати различных турниров, и тогда обогащение отклоняется
    целиком с названием фактического числа строк — частичное обогащение
    отдало бы разнородные записи, где не отличить пустое поле от
    отсутствующего.

    Сайт отдаёт максимум 20 результатов на один запрос без пагинации; при
    достижении потолка поле truncated равно true.
    """
    has_range = bool(date_from.strip()) or bool(date_to.strip())
    if has_range and not (date_from.strip() and date_to.strip()):
        raise InvalidInput("date_from и date_to задаются только вместе")
    if has_range and date.strip():
        raise InvalidInput("date и диапазон date_from/date_to задаются порознь")
    if not name.strip() and not date.strip() and not has_range:
        raise InvalidInput(
            "нужен хотя бы один из аргументов: name, date или диапазон дат"
        )
    for value, field in ((date, "date"), (date_from, "date_from"), (date_to, "date_to")):
        if value.strip() and not _DATE.fullmatch(value.strip()):
            raise InvalidInput(
                f"{field} должен быть в формате DD.MM.YYYY, получено {value!r}"
            )
    if date.strip():
        # Регулярка выше проверяет только форму DD.MM.YYYY; 99.99.2026 и
        # 31.02.2026 её проходят. Без этой проверки такая дата ушла бы в
        # запрос, а сайт на неё ответит пустым списком — неотличимо от
        # «турниров в этот день не было». Результат не нужен, нужна сама
        # проверка, поэтому она стоит здесь же, а не только у date_from/date_to.
        _day(date.strip(), "date")

    dates = (
        _dates_in_range(date_from.strip(), date_to.strip()) if has_range else [date]
    )

    found: dict[str, dict] = {}
    truncated = False
    for one in dates:
        page = parse_tournament_search(
            _client.post_ajax("get_tournaments_by_name", name=name, date=one)
        )
        truncated = truncated or page["truncated"]
        for row in page["tournaments"]:
            found.setdefault(row["id"], row)

    tournaments = list(found.values())
    if enrich and len(tournaments) > MAX_ENRICH_ROWS:
        raise InvalidInput(
            f"обогащение {len(tournaments)} строк потребовало бы столько же "
            f"запросов к сайту; максимум {MAX_ENRICH_ROWS}. Сузьте запрос "
            f"или запросите нужные турниры поимённо"
        )
    if enrich:
        for row in tournaments:
            detail = parse_tournament(
                _client.get_html("/tournaments/", {"id": row["id"]}), row["id"]
            )
            row["date"] = detail["date"]
            row["address"] = detail["address"]
            row["participants"] = detail["participants_count"]

    return {
        "total_found": len(tournaments),
        "truncated": truncated,
        "tournaments": tournaments,
    }


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

    Поле hand у строки standings — пометка руки игрока: "левая", "правая"
    или null. Сайт заводит под нерабочую руку отдельный профиль с отдельным
    идентификатором, поэтому один человек может встретиться в standings
    дважды, под разными player_id и с разными рейтингами; сервер не
    связывает такие профили.

    У турнира сумма дельт по строкам standings не равна нулю: в измерениях
    она была устойчиво положительной, от +26.45 до +58.52 (например, на
    турнире из семнадцати участников — ровно +58.52). Это свойство формулы
    сайта, а не ошибка разбора — искать ошибку у себя не нужно.

    Поле delta у строки standings может на сотую расходиться с дельтой
    того же турнира в профиле игрока (get_player: tournaments[].delta, а
    также сумма matches[].delta по этому турниру) — источники округляют
    по-разному. В замерах: -5.22 в standings против -5.23 в профиле для
    одного и того же игрока и турнира. Это не ошибка разбора и не
    расхождение данных, а разное округление на стороне сайта.

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


@mcp.tool()
@_reporting
def get_tournament_matches(tournament_id: str) -> dict:
    """Матчи, сыгранные на турнире.

    Страница турнира их не содержит — они есть только в профилях
    участников, поэтому инструмент сначала загружает саму страницу
    турнира, а затем профиль каждого участника: запросов на один больше,
    чем участников (профили плюс сама страница турнира), идут строго
    последовательно, и уже для семнадцати участников это минуты.

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
    matches = reconcile_matches(profiles, tournament_id)

    return {
        "tournament_id": tournament_id,
        "title": tournament["title"],
        "date": date,
        "participants_count": tournament["participants_count"],
        "matches": matches,
        "missing_profiles": missing,
    }


@mcp.tool()
@_reporting
def get_series(tournament_id: str, limit: int = 10) -> dict:
    """Турниры той же серии, включая запрошенный.

    Собственный список сайта ненадёжен: он возвращает то записи
    многолетней давности без свежих, то пустоту вовсе. Поэтому серия
    собирается из двух источников — списка на странице турнира и
    турниров с тем же названием из профилей участников, — и каждая
    запись помечена полем source: "page" или "participants".

    Запрошенный турнир в списке на странице отсутствует: там только
    другие турниры серии. Но он попадает в выдачу из профилей
    участников — его название совпадает само с собой. Это не ошибка:
    турнир — часть собственной серии, и молча убирать его было бы
    маленькой ложью.

    Совпадение по названию — эвристика: сравнение идёт по
    нормализованному ключу (без регистра, лишних пробелов и хвостовой
    точки или запятой), а не по точному равенству, — организаторы пишут
    названия неединообразно, то с точкой в конце, то без, то с пробелом
    перед ней. Даже с нормализацией это остаётся эвристикой, и она
    настроена скорее недобрать серию, чем додумать лишнее: слияние двух
    разных серий с почти одинаковыми названиями теоретически возможно,
    но в замерах не встретилось, а вот одна серия под тремя написаниями —
    встретилась сразу.

    Записи из профилей несут только id, date и source: address,
    organizers, participants и games у них равны null, а не отсутствуют
    — иначе не отличить «поля нет» от «значение пустое».

    missing_profiles перечисляет участников, чей профиль получить не
    удалось. Это вторая, независимая от эвристики совпадения названий,
    причина неполноты серии: турниры, которые нашлись бы только в
    профилях этих участников, в выдачу не попадут, и совпадение по
    названию здесь ни при чём.

    Сначала загружается сама страница турнира, а затем профиль каждого
    участника, запросы идут строго последовательно, поэтому цена — на
    один запрос больше, чем участников в составе.
    """
    if limit < 1:
        raise InvalidInput(f"limit должен быть положительным, получено {limit}")
    html = _client.get_html(
        "/tournaments/", {"id": _valid_id(tournament_id, "tournament_id")}
    )
    tournament = parse_tournament(html, tournament_id)
    key = _series_key(tournament["title"])

    events: dict[str, dict] = {}
    for entry in tournament["series"]:
        events[entry["id"]] = _series_event("page", entry["id"], entry["date"], entry)

    ids = [row["player_id"] for row in tournament["standings"]]
    profiles, missing = collect_profiles(_client, ids, include_matches=False)
    for profile in profiles.values():
        for played in profile["tournaments"]:
            if _series_key(played["title"]) != key:
                continue
            if played["tournament_id"] in events:
                continue
            events[played["tournament_id"]] = _series_event(
                "participants", played["tournament_id"], played["date"]
            )

    ordered = sorted(events.values(), key=lambda e: e["date"], reverse=True)
    return {
        "tournament_id": tournament_id,
        "title": tournament["title"],
        "events": ordered[:limit],
        "events_found": len(ordered),
        "missing_profiles": missing,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
