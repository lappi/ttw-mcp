# ttw-mcp: доработки по полевому отчёту — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть 14 пунктов полевого отчёта: урезать payload, перестать
молча врать рейтингом в таблице турнира, разобрать четыре формы технического
результата и добавить многозапросные инструменты для матчей турнира и серии.

**Architecture:** Между клиентом и инструментами появляется `collect.py` —
последовательный сбор нескольких профилей с дедупликацией в пределах одного
вызова. Рядом появляется `rating.py` — чистое восстановление рейтинга на
дату из уже разобранного профиля. Парсеры остаются чистыми функциями,
`server.py` остаётся единственным местом, знающим про MCP.

**Tech Stack:** Python 3.11+, `mcp[cli]>=2.0` (`MCPServer`, stdio), `httpx`,
`beautifulsoup4`, `soupsieve>=2.1`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-22-improvements-design.md`

## Global Constraints

- Python `>=3.11`. Зависимости не меняются: `mcp[cli]>=2.0`, `httpx`,
  `beautifulsoup4`, `soupsieve>=2.1`, плюс `pytest` в dev-группе.
- `BeautifulSoup(html, "html.parser")`. Никогда `lxml`.
- Даты наружу — ISO `YYYY-MM-DD`. Рейтинги и дельты — `float`, счётчики — `int`.
- Парсеры чистые: строка HTML на входе, словарь на выходе. Ни сети, ни файлов.
- `ttw_mcp/errors.py` и всё под `ttw_mcp/parsers/` не импортируют MCP.
  `ToolError` живёт только в `server.py`.
- Нет якоря — `ParseError`. Есть якорь и нет строк — пустой список.
  Никогда не возвращать правдоподобное значение для неопознанной разметки.
- Запросы строго последовательны. Ни `asyncio`, ни потоков.
- Русский текст остаётся русским, с полной орфографией.
- Фикстуры не коммитятся: `tests/fixtures/` в `.gitignore`.
- Ни одного ФИО в отслеживаемых файлах. Идентификаторы игроков — hex-строки,
  не персональные данные, и служат якорями в тестах.
- Урезание любых данных обязано сопровождаться полем с полным количеством:
  модель не должна принимать «показали 12» за «сыграл 12».

---

## File Structure

| Файл | Ответственность | Статус |
| --- | --- | --- |
| `ttw_mcp/parsers/common.py` | хелперы; `parse_score` учит четыре формы, добавляется `split_hand` | меняется |
| `ttw_mcp/parsers/player.py` | профиль; `summary` получает `seed_rating`, `first_rated_date` | меняется |
| `ttw_mcp/rating.py` | **новый**: восстановление рейтинга на дату, чистые функции |
| `ttw_mcp/collect.py` | **новый**: последовательный сбор профилей с дедупликацией |
| `ttw_mcp/server.py` | инструменты: новые параметры, два новых инструмента | меняется |
| `scripts/fetch_fixtures.py` | две новые фикстуры с редкими формами счёта | меняется |

---

### Task 1: Четыре формы технического результата

**Files:**
- Modify: `ttw_mcp/parsers/common.py`
- Test: `tests/test_parsers_common.py`

**Interfaces:**
- Consumes: ничего нового
- Produces: `parse_score(raw) -> tuple[int | None, int | None, str]`, где исход
  принимает значения `win`, `loss`, `walkover_win`, `walkover_loss`,
  `not_played`, `unparsed`

- [ ] **Step 1: Написать падающий тест**

В `tests/test_parsers_common.py` заменить параметризацию `test_parse_score_handles_walkover`:

```python
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3:1", (3, 1, "win")),
        ("0:2", (0, 2, "loss")),
        ("W:Тех", (None, None, "walkover_win")),
        ("W:L", (None, None, "walkover_win")),
        ("Тех:W", (None, None, "walkover_loss")),
        ("L:W", (None, None, "walkover_loss")),
        ("0:0", (None, None, "not_played")),
        ("3-1", (None, None, "unparsed")),
        ("", (None, None, "unparsed")),
    ],
)
def test_parse_score_knows_every_observed_form(raw, expected):
    # Четыре формы технического результата и «не сыгран» замерены на 4621
    # матче. Раньше три из них уходили в unparsed, и докстринг отправлял
    # пользователя искать изменившуюся вёрстку там, где её не было.
    assert parse_score(raw) == expected
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_parsers_common.py -k parse_score -v`
Expected: FAIL — `W:L`, `Тех:W`, `L:W` дают `walkover`, `0:0` даёт `loss`

- [ ] **Step 3: Реализация**

В `ttw_mcp/parsers/common.py` заменить константу `_WALKOVER` и функцию:

```python
_WALKOVER_WIN = frozenset({"W:Тех", "W:L"})
_WALKOVER_LOSS = frozenset({"Тех:W", "L:W"})
_NOT_PLAYED = "0:0"
```

```python
def parse_score(raw: str) -> tuple[int | None, int | None, str]:
    """Счёт матча и его исход.

    Сайт пишет технический результат четырьмя способами, по-разному для
    победившей и проигравшей стороны, и отдельно помечает несыгранный матч
    счётом 0:0 с нулевой дельтой. Все формы замерены на выборке в 4621 матч.

    Возвращает (партии за, партии против, исход). Для технического результата
    и несыгранного матча партии равны None, а исходная запись сохраняется
    вызывающим в score_raw.

    Исход "unparsed" означает форму, которой в замерах не было, то есть
    действительно изменившуюся вёрстку — в отличие от прежней версии, где
    туда попадали обычные технические поражения.
    """
    if raw == _NOT_PLAYED:
        return None, None, "not_played"
    if raw in _WALKOVER_WIN:
        return None, None, "walkover_win"
    if raw in _WALKOVER_LOSS:
        return None, None, "walkover_loss"
    match = _SCORE.match(raw)
    if match is None:
        return None, None, "unparsed"
    score_for, score_against = int(match.group(1)), int(match.group(2))
    return score_for, score_against, "win" if score_for > score_against else "loss"
```

- [ ] **Step 4: Запустить тесты файла**

Run: `uv run pytest tests/test_parsers_common.py -v`
Expected: PASS. Прежний тест на `walkover` заменён, число тестов в файле
меняется с 23 на 29.

- [ ] **Step 5: Починить сломанные тесты соседних файлов**

`tests/test_parsers_player.py` и `tests/test_parsers_head_to_head.py`
сверяют `result == "walkover"`. Заменить на `"walkover_win"`.
Run: `uv run pytest -q`
Expected: PASS, 117.

- [ ] **Step 6: Коммит**

```bash
git add ttw_mcp/parsers/common.py tests/
git commit -m "fix: recognise all four walkover spellings and the not-played score"
```

---

### Task 2: Фикстуры с редкими формами

**Files:**
- Modify: `scripts/fetch_fixtures.py`
- Modify: `tests/test_fixtures.py`
- Test: `tests/test_parsers_player.py`

**Interfaces:**
- Consumes: `parse_score` из Task 1
- Produces: фикстуры `player_walkover_loss.html.gz`, `player_walkover_tech.html.gz`

- [ ] **Step 1: Добавить страницы в скрипт**

В `PAGES` в `scripts/fetch_fixtures.py`:

```python
    ("player_walkover_loss.html.gz", "GET", "/players/", {"id": "44d227e"}),
    ("player_walkover_tech.html.gz", "GET", "/players/", {"id": "23a3d0d"}),
```

Профили крупные (329 КБ и 260 КБ), поэтому сжатые — загрузчик `conftest.py`
читает `.gz` прозрачно.

- [ ] **Step 2: Скачать**

Run: `uv run python scripts/fetch_fixtures.py`
Expected: тринадцать строк вывода, около полутора минут.

- [ ] **Step 3: Написать тест на реальных формах**

В `tests/test_parsers_player.py`:

```python
def test_all_walkover_forms_parse_on_real_profiles(load_fixture):
    # Формы распределены по двум профилям: ни один не содержит все четыре.
    loss = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    tech = parse_player_profile(load_fixture("player_walkover_tech.html"), "23a3d0d")

    def by_raw(profile, raw):
        return [m for m in profile["matches"] if m["score_raw"] == raw]

    assert len(by_raw(loss, "W:L")) == 1
    assert by_raw(loss, "W:L")[0]["result"] == "walkover_win"
    assert len(by_raw(loss, "L:W")) == 1
    assert by_raw(loss, "L:W")[0]["result"] == "walkover_loss"
    assert len(by_raw(tech, "Тех:W")) == 4
    assert all(m["result"] == "walkover_loss" for m in by_raw(tech, "Тех:W"))

    # Ни одного действительно неопознанного счёта на 2000 матчей.
    assert [m for m in loss["matches"] if m["result"] == "unparsed"] == []
    assert [m for m in tech["matches"] if m["result"] == "unparsed"] == []


def test_not_played_is_separated_from_losses(load_fixture):
    loss = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    void = [m for m in loss["matches"] if m["result"] == "not_played"]
    assert len(void) == 2
    assert all(m["score_raw"] == "0:0" for m in void)
    assert all(m["delta"] == 0.0 for m in void)
```

- [ ] **Step 4: Добавить фикстуры в CASES**

В `tests/test_fixtures.py`:

```python
    ("player_walkover_loss.html", "44d227e"),
    ("player_walkover_tech.html", "23a3d0d"),
```

- [ ] **Step 5: Прогон**

Run: `uv run pytest -q`
Expected: PASS, 121.

- [ ] **Step 6: Коммит**

```bash
git add scripts/fetch_fixtures.py tests/
git commit -m "test: fixtures covering every walkover spelling"
```

---

### Task 3: Пометка руки отдельным полем

**Files:**
- Modify: `ttw_mcp/parsers/common.py`
- Modify: `ttw_mcp/parsers/search.py`, `ttw_mcp/parsers/tournament.py`
- Test: `tests/test_parsers_common.py`, `tests/test_parsers_search.py`, `tests/test_parsers_tournament.py`

**Interfaces:**
- Consumes: `clean` из `common.py`
- Produces: `split_hand(name) -> tuple[str, str | None]`

- [ ] **Step 1: Написать падающий тест хелпера**

В `tests/test_parsers_common.py`:

```python
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Фамилия Имя Отчество", ("Фамилия Имя Отчество", None)),
        ("Фамилия Имя Отчество левая", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество (левая)", ("Фамилия Имя Отчество", "левая")),
        ("Фамилия Имя Отчество (правая)", ("Фамилия Имя Отчество", "правая")),
    ],
)
def test_split_hand_handles_both_site_forms(raw, expected):
    # Сайт пишет пометку двумя способами: в скобках и без них.
    assert split_hand(raw) == expected
```

Добавить `split_hand` в импорт файла.

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_parsers_common.py -k split_hand -v`
Expected: FAIL — `ImportError: cannot import name 'split_hand'`

- [ ] **Step 3: Реализация**

В `ttw_mcp/parsers/common.py`:

```python
_HAND = re.compile(r"\s*\(?(левая|правая)\)?\s*$")


def split_hand(name: str) -> tuple[str, str | None]:
    """Отделяет пометку руки от ФИО.

    Сайт добавляет её двумя способами — «<ФИО> левая» и «<ФИО> (левая)» —
    и заводит под такой профиль отдельный идентификатор. Оставлять пометку
    внутри имени значит мешать сравнение имён и скрывать от потребителя, что
    игрок выступает нерабочей рукой с существенно другим рейтингом.
    """
    match = _HAND.search(name)
    if match is None:
        return name, None
    return name[: match.start()].strip(), match.group(1)
```

- [ ] **Step 4: Применить в парсерах имён**

В `ttw_mcp/parsers/search.py`, в `parse_player_search`, заменить
`"name": text_of(link),` на:

```python
        player_name, hand = split_hand(text_of(link))
```

и в словарь строки добавить `"name": player_name, "hand": hand,`.

То же в `ttw_mcp/parsers/tournament.py` в разборе строки таблицы. Импортировать
`split_hand` в обоих файлах.

- [ ] **Step 5: Тесты на реальных фикстурах**

В `tests/test_parsers_search.py`:

```python
def test_hand_marker_is_split_out_of_the_name(load_fixture):
    result = parse_player_search(load_fixture("search_players_many.html"), limit=200)
    with_hand = [p for p in result["players"] if p["hand"]]
    assert with_hand, "в этой выдаче есть игрок с пометкой руки"
    assert all("(" not in p["name"] for p in with_hand)
    assert all(p["hand"] in ("левая", "правая") for p in with_hand)
```

В `tests/test_parsers_tournament.py`:

```python
def test_hand_marker_in_standings(load_fixture):
    t = parse_tournament(load_fixture("tournament.html"), "6ad412a")
    with_hand = [r for r in t["standings"] if r["hand"]]
    assert len(with_hand) == 1
    assert with_hand[0]["hand"] == "левая"
    assert not with_hand[0]["name"].endswith("левая")
```

- [ ] **Step 6: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 127.

```bash
git add ttw_mcp/parsers/ tests/
git commit -m "feat: split the playing-hand marker out of player names"
```

---

### Task 4: Стартовый рейтинг и дата первого старта

**Files:**
- Modify: `ttw_mcp/parsers/player.py`
- Test: `tests/test_parsers_player.py`

**Interfaces:**
- Consumes: `_parse_summary`, `_parse_all_games` из `player.py`
- Produces: `summary["seed_rating"]: float | None`, `summary["first_rated_date"]: str | None`

- [ ] **Step 1: Написать падающий тест**

```python
def test_seed_rating_is_reconstructed_for_short_history(novice, veteran):
    # rating_after самого раннего периода минус его дельта. Метод даёт
    # круглые значения, что его и подтверждает: система сажает новичка
    # на целое число.
    assert novice["summary"]["seed_rating"] == pytest.approx(90.00)
    assert novice["summary"]["first_rated_date"] == "2026-09-07"
    assert veteran["summary"]["seed_rating"] == pytest.approx(115.00)
    assert veteran["summary"]["first_rated_date"] == "2025-09-15"


def test_seed_rating_is_null_when_history_is_truncated(load_fixture):
    # У этого игрока 87 периодов, а rated_periods упёрлось в 30: значит
    # самый ранний показанный период не является первым, и восстанавливать
    # по нему стартовый рейтинг нельзя. Честный null вместо выдумки.
    deep = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    assert deep["summary"]["rated_periods"] == 30
    assert len(deep["periods"]) == 87
    assert deep["summary"]["seed_rating"] is None
    assert deep["summary"]["first_rated_date"] is None
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_parsers_player.py -k seed_rating -v`
Expected: FAIL — `KeyError: 'seed_rating'`

- [ ] **Step 3: Реализация**

В `ttw_mcp/parsers/player.py`, в `parse_player_profile`, после сбора
`periods` и `summary`:

```python
RATED_PERIODS_CAP = 30


def _seed(periods: list[dict], summary: dict) -> tuple[float | None, str | None]:
    """Стартовый рейтинг и дата первого обсчёта.

    Восстанавливается как rating_after самого раннего периода минус его
    дельта. Если rated_periods упёрлось в потолок 30, самый ранний
    показанный период не первый, и оба значения неизвестны.
    """
    if not periods or summary.get("rated_periods", 0) >= RATED_PERIODS_CAP:
        return None, None
    earliest = periods[-1]
    return round(earliest["rating_after"] - earliest["delta"], 2), earliest["start"]
```

и в собираемый `summary`:

```python
    seed_rating, first_rated_date = _seed(periods, summary)
    summary["seed_rating"] = seed_rating
    summary["first_rated_date"] = first_rated_date
```

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 129.

```bash
git add ttw_mcp/parsers/player.py tests/test_parsers_player.py
git commit -m "feat: reconstruct the seed rating and first rated date"
```

---

### Task 5: Восстановление рейтинга на дату

**Files:**
- Create: `ttw_mcp/rating.py`
- Test: `tests/test_rating.py`

**Interfaces:**
- Consumes: словарь профиля от `parse_player_profile`
- Produces: `rating_at_event(profile: dict, date: str) -> float | None`,
  `annotate_matches(profile: dict) -> None`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_rating.py`:

```python
import pytest

from ttw_mcp.parsers.player import parse_player_profile
from ttw_mcp.rating import annotate_matches, rating_at_event


def test_rating_at_event_differs_from_the_current_one(load_fixture):
    # Турнир 6ad412a прошёл 2026-09-13. Таблица турнира показывает для этого
    # игрока 84.48 — его СЕГОДНЯШНИЙ рейтинг. На момент турнира было 90.00.
    # Ради этой разницы инструмент и существует.
    profile = parse_player_profile(load_fixture("player_novice.html"), "1c18ed8")
    assert rating_at_event(profile, "2026-09-13") == pytest.approx(90.00)
    assert profile["current_rating"] != pytest.approx(90.00)


def test_rating_at_event_is_none_outside_known_history(load_fixture):
    profile = parse_player_profile(load_fixture("player_novice.html"), "1c18ed8")
    assert rating_at_event(profile, "2020-01-01") is None


def test_rating_at_event_handles_two_tournaments_in_one_period(load_fixture):
    # У глубокого профиля 146 турниров на 87 периодов, то есть в периоде их
    # бывает больше одного. Вычитать надо дельты всех турниров периода начиная
    # с даты события, а не только дельту самого события.
    deep = parse_player_profile(load_fixture("player_walkover_loss.html"), "44d227e")
    crowded = None
    for period in deep["periods"]:
        inside = [t for t in deep["tournaments"] if period["start"] <= t["date"] <= period["end"]]
        if len(inside) > 1:
            crowded = (period, sorted(inside, key=lambda t: t["date"]))
            break
    assert crowded is not None, "в этом профиле есть период с несколькими турнирами"
    period, inside = crowded
    expected = period["rating_after"] - sum(t["delta"] for t in inside)
    assert rating_at_event(deep, inside[0]["date"]) == pytest.approx(expected, abs=0.01)


def test_annotate_matches_fills_player_rating(load_fixture):
    profile = parse_player_profile(load_fixture("player_novice.html"), "1c18ed8")
    annotate_matches(profile)
    assert all("player_rating_at_match" in m for m in profile["matches"])
    first = profile["matches"][0]
    assert first["player_rating_at_match"] == pytest.approx(
        rating_at_event(profile, first["date"])
    )
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_rating.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ttw_mcp.rating'`

- [ ] **Step 3: Реализация**

Создать `ttw_mcp/rating.py`:

```python
"""Восстановление рейтинга игрока на дату события.

Ни одна страница сайта не отдаёт рейтинг на момент турнира: и таблица
турнира, и шапка профиля показывают сегодняшнее значение. Разница бывает
в сотни пунктов, поэтому любая метрика вида «сила поля на дату» по сырым
данным сайта неверна.

Всё здесь — чистые функции над уже разобранным профилем, без сети.
"""


def rating_at_event(profile: dict, date: str) -> float | None:
    """Рейтинг игрока непосредственно перед событием указанной даты.

    Берётся недельный период, покрывающий дату, и из его итогового рейтинга
    вычитаются дельты всех турниров игрока в этом периоде, случившихся не
    раньше события.

    Возвращает None, когда ответа нет: период не найден (история усечена)
    либо в периоде есть другой турнир в тот же день, а порядок внутри дня
    сайт не сообщает. Приближение здесь было бы правдоподобной выдумкой.
    """
    period = next(
        (p for p in profile.get("periods", []) if p["start"] <= date <= p["end"]),
        None,
    )
    if period is None:
        return None
    inside = [
        t
        for t in profile.get("tournaments", [])
        if period["start"] <= t["date"] <= period["end"]
    ]
    if sum(1 for t in inside if t["date"] == date) > 1:
        return None
    after = sum(t["delta"] for t in inside if t["date"] >= date)
    return round(period["rating_after"] - after, 2)


def annotate_matches(profile: dict) -> None:
    """Проставляет player_rating_at_match каждому матчу профиля.

    Рейтинг соперника сайт отдаёт с двумя знаками, а собственный — нет; без
    этого поля матч нельзя сопоставить по силе сторон, и в полевом отчёте
    датасет на 169 матчей собирался вручную именно из-за его отсутствия.
    """
    cache: dict[str, float | None] = {}
    for match in profile.get("matches", []):
        date = match["date"]
        if date not in cache:
            cache[date] = rating_at_event(profile, date)
        match["player_rating_at_match"] = cache[date]
```

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest tests/test_rating.py -v`
Expected: PASS, 4 теста.
Run: `uv run pytest -q`
Expected: PASS, 133.

```bash
git add ttw_mcp/rating.py tests/test_rating.py
git commit -m "feat: reconstruct a player's rating at the time of an event"
```

---

### Task 6: Сборщик профилей

**Files:**
- Create: `ttw_mcp/collect.py`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `TtwClient.get_html`, `parse_player_profile`
- Produces: `collect_profiles(client, player_ids, *, include_matches=True) -> tuple[dict[str, dict], list[str]]`
  — словарь `id -> профиль` и список идентификаторов, которые получить не удалось

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_collect.py`:

```python
import pytest

from ttw_mcp.collect import collect_profiles
from ttw_mcp.errors import UpstreamError


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
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_collect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ttw_mcp.collect'`

- [ ] **Step 3: Реализация**

Создать `ttw_mcp/collect.py`:

```python
"""Сбор нескольких профилей для многозапросных инструментов.

Сайт отвечает за 4–17 секунд и просит себя не обходить, поэтому запросы
идут строго последовательно, а один идентификатор запрашивается один раз
за вызов. Между вызовами ничего не хранится: состояния на диске у сервера
нет по устройству.
"""

from collections.abc import Iterable

from ttw_mcp.errors import TtwError
from ttw_mcp.parsers.player import parse_player_profile


def collect_profiles(
    client,
    player_ids: Iterable[str],
    *,
    include_matches: bool = True,
) -> tuple[dict[str, dict], list[str]]:
    """Собирает профили по списку идентификаторов.

    Возвращает пару: словарь идентификатор -> профиль и список тех, кого
    получить не удалось. Ошибка на одном игроке не отменяет остальных —
    состав из восемнадцати не должен обнуляться из-за одного недоступного
    профиля, — но и умалчивать о потере нельзя, поэтому список возвращается
    отдельно, а вызывающий инструмент сообщает о нём в ответе.
    """
    profiles: dict[str, dict] = {}
    missing: list[str] = []
    for player_id in player_ids:
        if player_id in profiles or player_id in missing:
            continue
        try:
            html = client.get_html("/players/", {"id": player_id})
            profiles[player_id] = parse_player_profile(
                html, player_id, include_matches=include_matches
            )
        except TtwError:
            missing.append(player_id)
    return profiles, missing
```

**Примечание для исполнителя:** `parse_player_profile` пока не принимает
`include_matches` — этот параметр добавляется в Task 7. Порядок задач такой
намеренно: сборщик тестируется первым, а до Task 7 последний тест этого
файла будет падать. Реализуй `collect.py` целиком, но последний тест
(`test_include_matches_false_is_passed_through`) помети
`@pytest.mark.xfail(reason="include_matches появится в Task 7", strict=True)`
и сними пометку в Task 7.

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest tests/test_collect.py -v`
Expected: PASS, 3 теста плюс один xfail.
Run: `uv run pytest -q`
Expected: PASS, 136 плюс 1 xfailed.

```bash
git add ttw_mcp/collect.py tests/test_collect.py
git commit -m "feat: sequential profile collector with per-call de-duplication"
```

---

### Task 7: Урезание payload профиля

**Files:**
- Modify: `ttw_mcp/parsers/player.py`, `ttw_mcp/server.py`
- Test: `tests/test_parsers_player.py`, `tests/test_server.py`, `tests/test_collect.py`

**Interfaces:**
- Consumes: `parse_player_profile`
- Produces: `parse_player_profile(html, player_id, *, include_matches=True, matches_since=None)`;
  ответ всегда содержит `matches_total: int` и `best_wins_total: int`

- [ ] **Step 1: Написать падающий тест парсера**

```python
def test_matches_can_be_omitted_but_the_count_survives(load_fixture):
    # 93 % объёма профиля — это matches. Но выкинуть их молча нельзя:
    # модель не отличит «сыграл 12» от «показали 12 из 1891».
    slim = parse_player_profile(
        load_fixture("player_veteran.html"), "66f1645", include_matches=False
    )
    assert "matches" not in slim
    assert "best_wins" not in slim
    assert slim["matches_total"] == 106
    assert slim["best_wins_total"] == 5
    assert len(slim["periods"]) == 13


def test_matches_since_filters_but_reports_the_whole(load_fixture):
    recent = parse_player_profile(
        load_fixture("player_veteran.html"), "66f1645", matches_since="2026-09-01"
    )
    assert recent["matches_total"] == 106
    assert len(recent["matches"]) < 106
    assert all(m["date"] >= "2026-09-01" for m in recent["matches"])
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_parsers_player.py -k "omitted or since" -v`
Expected: FAIL — `parse_player_profile() got an unexpected keyword argument`

- [ ] **Step 3: Реализация в парсере**

Сигнатуру `parse_player_profile` дополнить:

```python
def parse_player_profile(
    html: str,
    player_id: str,
    *,
    include_matches: bool = True,
    matches_since: str | None = None,
) -> dict:
```

После сбора `matches` и `best_wins`, перед формированием результата:

```python
    result["matches_total"] = len(matches)
    result["best_wins_total"] = len(best_wins)
    if include_matches:
        if matches_since is not None:
            matches = [m for m in matches if m["date"] >= matches_since]
        result["matches"] = matches
        result["best_wins"] = best_wins
```

Ключи `matches` и `best_wins` при `include_matches=False` отсутствуют, а не
равны пустому списку: пустой список означал бы «матчей нет».

- [ ] **Step 4: Пробросить параметры в инструмент**

В `ttw_mcp/server.py`:

```python
@mcp.tool()
@_reporting
def get_player(
    player_id: str, include_matches: bool = True, matches_since: str = ""
) -> dict:
```

с проверкой формата даты тем же `_DATE`-подобным правилом, что и в
`search_tournaments`, но для ISO:

```python
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
```

```python
    since = matches_since.strip() or None
    if since is not None and not _ISO_DATE.fullmatch(since):
        raise InvalidInput(
            f"matches_since должен быть в формате YYYY-MM-DD, получено {matches_since!r}"
        )
```

- [ ] **Step 5: Тест инструмента и снятие xfail**

В `tests/test_server.py`:

```python
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
```

В `tests/test_collect.py` снять `@pytest.mark.xfail` с
`test_include_matches_false_is_passed_through`.

- [ ] **Step 6: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 140.

```bash
git add ttw_mcp/parsers/player.py ttw_mcp/server.py tests/
git commit -m "feat: let get_player skip or date-limit the match list"
```

---

### Task 8: Рейтинг игрока на момент матча

**Files:**
- Modify: `ttw_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `annotate_matches` из `ttw_mcp/rating.py`
- Produces: каждый элемент `matches` получает `player_rating_at_match: float | None`

- [ ] **Step 1: Написать падающий тест**

```python
def test_matches_carry_the_players_own_rating(stub, load_fixture):
    # Рейтинг соперника сайт даёт, свой — нет. Без него матч нельзя
    # сопоставить по силе сторон, и в полевом отчёте датасет на 169 матчей
    # собирался вручную именно из-за этого.
    stub(load_fixture("player_novice.html"))
    result = server.get_player("1c18ed8")
    assert all("player_rating_at_match" in m for m in result["matches"])
    assert any(m["player_rating_at_match"] is not None for m in result["matches"])
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_server.py -k own_rating -v`
Expected: FAIL — `KeyError: 'player_rating_at_match'`

- [ ] **Step 3: Реализация**

В `ttw_mcp/server.py`, в `get_player`, после разбора:

```python
    profile = parse_player_profile(
        html, player_id, include_matches=include_matches, matches_since=since
    )
    if include_matches:
        annotate_matches(profile)
    return profile
```

Импортировать `annotate_matches` из `ttw_mcp.rating`.

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 141.

```bash
git add ttw_mcp/server.py tests/test_server.py
git commit -m "feat: annotate each match with the player's own rating at the time"
```

---

### Task 9: Честный рейтинг в таблице турнира

**Files:**
- Modify: `ttw_mcp/parsers/tournament.py`, `ttw_mcp/server.py`
- Test: `tests/test_parsers_tournament.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `collect_profiles`, `rating_at_event`
- Produces: `standings[].rating_current` (переименование), `standings[].rating_at_event`,
  `ratings_at_event_resolved: int | None`

- [ ] **Step 1: Переименовать поле и поправить тесты**

В `ttw_mcp/parsers/tournament.py`, в сборке строки таблицы:

```python
                "rating_current": parse_number(text_of(row.select_one("td.player-rating-cell"))),
```

вместо прежнего `"rating": ...`. Ключ переименован, потому что сайт отдаёт
в этой ячейке сегодняшнее значение, а имя `rating` читается как «рейтинг
на турнире» и расходится с истиной на сотни пунктов.

В `tests/test_parsers_tournament.py` заменить три обращения:

```python
    assert tournament["standings"][0]["rating_current"] == pytest.approx(195.96)
    assert last["rating_current"] == pytest.approx(84.48)
```

и в тесте серии, если он обращается к полю. Числа сверить с фикстурой: она
пересобиралась, и значения могли сдвинуться. Расхождение сообщить, а не
подгонять.

- [ ] **Step 2: Написать падающий тест инструмента**

В `tests/test_server.py`:

```python
def test_ratings_at_event_differ_from_current(stub_multi, load_fixture):
    # Турнир 2026-09-13. В таблице у этого игрока стоит 84.48 — сегодняшнее
    # значение. На момент турнира было 90.00. Разница и есть предмет правки.
    stub_multi(
        {"6ad412a": load_fixture("tournament.html"),
         "1c18ed8": load_fixture("player_novice.html")}
    )
    result = server.get_tournament("6ad412a", ratings_at_event=True)
    row = next(r for r in result["standings"] if r["player_id"] == "1c18ed8")
    assert row["rating_current"] == pytest.approx(84.48)
    assert row["rating_at_event"] == pytest.approx(90.00)
    assert result["ratings_at_event_resolved"] >= 1


def test_ratings_at_event_is_off_by_default(stub, load_fixture):
    client = stub(load_fixture("tournament.html"))
    result = server.get_tournament("6ad412a")
    assert len(client.calls) == 1
    assert "rating_at_event" not in result["standings"][0]
    assert result["ratings_at_event_resolved"] is None
```

`stub_multi` — новая фикстура в `tests/test_server.py`, отдающая разные
страницы по значению `params["id"]`:

```python
@pytest.fixture
def stub_multi(monkeypatch):
    def install(pages: dict[str, str]):
        class MultiStub:
            def __init__(self):
                self.calls = []

            def get_html(self, path, params):
                key = params["id"]
                self.calls.append(key)
                return pages[key]

        client = MultiStub()
        monkeypatch.setattr(server, "_client", client)
        return client

    return install
```

- [ ] **Step 3: Реализация**

В `ttw_mcp/server.py`:

```python
@mcp.tool()
@_reporting
def get_tournament(tournament_id: str, ratings_at_event: bool = False) -> dict:
```

После разбора турнира:

```python
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
```

**Осторожно:** `collect_profiles` вызывается с `include_matches=False` —
для восстановления рейтинга нужны только `periods` и `tournaments`, а
матчи составили бы мегабайты трафика впустую.

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 144.

```bash
git add ttw_mcp/parsers/tournament.py ttw_mcp/server.py tests/
git commit -m "fix: tournament standings rating was today's value, not the event's"
```

---

### Task 10: Матчи турнира

**Files:**
- Modify: `ttw_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `parse_tournament`, `collect_profiles`
- Produces: инструмент `get_tournament_matches(tournament_id) -> dict`

- [ ] **Step 1: Написать падающий тест**

```python
def test_tournament_matches_are_collected_from_participants(stub_multi, load_fixture):
    # Страница турнира матчей не содержит — они лежат в профилях участников.
    stub_multi(
        {"6ad412a": load_fixture("tournament.html"),
         "1c18ed8": load_fixture("player_novice.html"),
         "66f1645": load_fixture("player_veteran.html")}
    )
    result = server.get_tournament_matches("6ad412a")
    assert result["date"] == "2026-09-13"
    assert all(m["date"] == "2026-09-13" for m in result["matches"])
    # Каждый матч отдаётся один раз, хотя присутствует в двух профилях.
    pairs = {tuple(sorted((m["player_id"], m["opponent_id"]))) for m in result["matches"]}
    assert len(pairs) == len(result["matches"])
    assert result["missing_profiles"], "в стабе есть не все участники — это честно сообщается"


def test_mirror_mismatch_is_loud(stub_multi, load_fixture):
    # Один матч виден с двух сторон. Если счета не зеркальны, выбирать
    # версию молча нельзя: это изменившаяся вёрстка или ошибка разбора.
    broken = load_fixture("player_veteran.html").replace(
        'class="game-score-cell">2:0</td>', 'class="game-score-cell">2:1</td>', 1
    )
    stub_multi(
        {"6ad412a": load_fixture("tournament.html"),
         "1c18ed8": load_fixture("player_novice.html"),
         "66f1645": broken}
    )
    with pytest.raises(ToolError, match="ParseError"):
        server.get_tournament_matches("6ad412a")
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_server.py -k tournament_matches -v`
Expected: FAIL — `AttributeError: module 'ttw_mcp.server' has no attribute 'get_tournament_matches'`

- [ ] **Step 3: Реализация**

В `ttw_mcp/server.py`:

```python
@mcp.tool()
@_reporting
def get_tournament_matches(tournament_id: str) -> dict:
    """Матчи, сыгранные на турнире.

    Страница турнира их не содержит — они есть только в профилях
    участников, поэтому инструмент загружает профиль каждого: запросов
    столько же, сколько участников, для восемнадцати это полторы минуты.

    Каждый матч присутствует в профилях обоих игроков и отдаётся один раз.
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

    seen: dict[tuple[str, str], dict] = {}
    for player_id, profile in profiles.items():
        for match in profile["matches"]:
            if match["date"] != date:
                continue
            key = tuple(sorted((player_id, match["opponent_id"])))
            entry = {
                "player_id": player_id,
                "opponent_id": match["opponent_id"],
                "date": match["date"],
                "score_raw": match["score_raw"],
                "score_for": match["score_for"],
                "score_against": match["score_against"],
                "result": match["result"],
                "delta": match["delta"],
            }
            if key not in seen:
                seen[key] = entry
                continue
            other = seen[key]
            mirrored = (
                other["player_id"] == match["opponent_id"]
                and other["score_for"] == match["score_against"]
                and other["score_against"] == match["score_for"]
            )
            if not mirrored:
                raise ParseError(
                    "get_tournament_matches",
                    "game-score-cell",
                    f"счета с двух сторон не совпали: {other} против {entry}",
                )

    return {
        "tournament_id": tournament_id,
        "title": tournament["title"],
        "date": date,
        "participants": tournament["participants_count"],
        "matches": list(seen.values()),
        "missing_profiles": missing,
    }
```

Импортировать `ParseError` в `server.py`.

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 146.

```bash
git add ttw_mcp/server.py tests/test_server.py
git commit -m "feat: reconstruct a tournament's matches from participant profiles"
```

---

### Task 11: Серия турниров

**Files:**
- Modify: `ttw_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `parse_tournament`, `collect_profiles`
- Produces: инструмент `get_series(tournament_id, limit=10) -> dict`

- [ ] **Step 1: Написать падающий тест**

```python
def test_series_merges_page_and_participants(stub_multi, load_fixture):
    stub_multi(
        {"6ad412a": load_fixture("tournament.html"),
         "1c18ed8": load_fixture("player_novice.html"),
         "66f1645": load_fixture("player_veteran.html")}
    )
    result = server.get_series("6ad412a", limit=10)
    assert result["title"] == "Санкт Петербург. Турнир Энерджи Арена."
    assert result["events"], "серия не пуста"
    assert all(e["source"] in ("page", "participants") for e in result["events"])
    # Порядок от свежего к старому и без повторов.
    dates = [e["date"] for e in result["events"]]
    assert dates == sorted(dates, reverse=True)
    assert len({e["id"] for e in result["events"]}) == len(result["events"])


def test_series_says_where_each_event_came_from(stub_multi, load_fixture):
    # Собственный список сайта ненадёжен: в полевом отчёте он вернул две
    # записи 2024 года и ни одной за 2026. Поэтому источник помечается.
    stub_multi(
        {"6ad412a": load_fixture("tournament.html"),
         "1c18ed8": load_fixture("player_novice.html")}
    )
    result = server.get_series("6ad412a")
    assert {e["source"] for e in result["events"]} <= {"page", "participants"}
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_server.py -k series -v`
Expected: FAIL — `AttributeError: module 'ttw_mcp.server' has no attribute 'get_series'`

- [ ] **Step 3: Реализация**

```python
@mcp.tool()
@_reporting
def get_series(tournament_id: str, limit: int = 10) -> dict:
    """Другие турниры той же серии.

    Собственный список сайта ненадёжен: он возвращает то записи многолетней
    давности без свежих, то пустоту. Поэтому серия собирается из двух
    источников — списка на странице турнира и турниров с тем же названием
    из профилей участников, — и каждая запись помечена полем source.

    Совпадение по названию это эвристика: организаторы пишут названия
    неединообразно, вплоть до опечаток в городе. Инструмент скорее вернёт
    короткий список, чем додумает недостающее.

    Загружает профили участников, поэтому стоит столько же запросов, сколько
    их в составе.
    """
    if limit < 1:
        raise InvalidInput(f"limit должен быть положительным, получено {limit}")
    html = _client.get_html(
        "/tournaments/", {"id": _valid_id(tournament_id, "tournament_id")}
    )
    tournament = parse_tournament(html, tournament_id)

    events: dict[str, dict] = {}
    for entry in tournament["series"]:
        events[entry["id"]] = {**entry, "source": "page"}

    ids = [row["player_id"] for row in tournament["standings"]]
    profiles, missing = collect_profiles(_client, ids, include_matches=False)
    for profile in profiles.values():
        for played in profile["tournaments"]:
            if played["title"] != tournament["title"]:
                continue
            if played["tournament_id"] in events:
                continue
            events[played["tournament_id"]] = {
                "id": played["tournament_id"],
                "date": played["date"],
                "source": "participants",
            }

    ordered = sorted(events.values(), key=lambda e: e["date"], reverse=True)
    return {
        "tournament_id": tournament_id,
        "title": tournament["title"],
        "events": ordered[:limit],
        "events_found": len(ordered),
        "missing_profiles": missing,
    }
```

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 148.

```bash
git add ttw_mcp/server.py tests/test_server.py
git commit -m "feat: assemble a tournament series from two sources"
```

---

### Task 12: Диапазон дат и обогащение в поиске турниров

**Files:**
- Modify: `ttw_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Produces: `search_tournaments(name="", date="", date_from="", date_to="", enrich=False)`

- [ ] **Step 1: Написать падающий тест**

```python
def test_date_range_queries_every_day_in_it(stub, load_fixture):
    client = stub(load_fixture("search_tournaments.html"))
    server.search_tournaments(date_from="01.09.2026", date_to="03.09.2026")
    # По запросу на каждый день диапазона: ajax принимает одну дату.
    assert len(client.calls) == 3


def test_range_longer_than_two_weeks_is_refused(stub):
    client = stub()
    with pytest.raises(ToolError, match="14"):
        server.search_tournaments(date_from="01.01.2026", date_to="01.03.2026")
    assert client.calls == []


def test_enrich_costs_a_request_per_row(stub_multi, load_fixture):
    pages = {"6ad412a": load_fixture("tournament.html")}
    client = stub_multi(pages)
    # Подменяем ajax-ответ одной строкой, ссылающейся на известный турнир.
    client.ajax = '<div>1. <a href="/tournaments/?id=6ad412a">Турнир</a></div>'
    result = server.search_tournaments(name="турнир", enrich=True)
    assert result["tournaments"][0]["date"] == "2026-09-13"
    assert result["tournaments"][0]["participants"] == 17
```

`stub_multi` из Task 9 дополняется поддержкой ajax — замените класс внутри
фикстуры на:

```python
        class MultiStub:
            def __init__(self):
                self.calls = []
                self.ajax = ""

            def get_html(self, path, params):
                self.calls.append(params["id"])
                return pages[params["id"]]

            def post_ajax(self, action, **fields):
                self.calls.append(f"{action}:{fields.get('date', '')}")
                return self.ajax
```

Теперь `client.calls` содержит и обращения к ajax, и загрузки турниров,
поэтому тест диапазона считает именно ajax-вызовы.

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_server.py -k "date_range or enrich or two_weeks" -v`
Expected: FAIL — `got an unexpected keyword argument 'date_from'`

- [ ] **Step 3: Реализация**

```python
MAX_RANGE_DAYS = 14
```

```python
def _dates_in_range(date_from: str, date_to: str) -> list[str]:
    """Перечисляет даты диапазона в формате сайта.

    Ajax принимает единственную дату, поэтому диапазон стоит по запросу на
    день. Потолок в две недели выбран как компромисс: сайт отвечает по
    4–17 секунд и просит себя не обходить, а молча выполнить перебор на год
    значило бы превратить инструмент в краулер.
    """
    start = datetime.strptime(date_from, "%d.%m.%Y").date()
    end = datetime.strptime(date_to, "%d.%m.%Y").date()
    if end < start:
        raise InvalidInput(f"date_to {date_to} раньше date_from {date_from}")
    days = (end - start).days + 1
    if days > MAX_RANGE_DAYS:
        raise InvalidInput(
            f"диапазон в {days} дней потребовал бы {days} запросов к сайту; "
            f"максимум {MAX_RANGE_DAYS}"
        )
    return [(start + timedelta(days=i)).strftime("%d.%m.%Y") for i in range(days)]
```

Полная замена `search_tournaments`:

```python
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
    а не в ISO — это единственное место, где наружу смотрит формат
    источника, потому что значение уходит в его же поисковую форму.

    date_from и date_to задают диапазон и стоят по запросу на каждый день:
    ajax принимает только одну дату. Диапазон длиннее двух недель
    отклоняется, чтобы инструмент не превратился в краулер по сайту,
    который просит себя не обходить.

    enrich=True добавляет каждой строке дату, адрес и число участников,
    загружая турнир отдельно — ещё один запрос на строку, до двадцати.

    Сайт отдаёт максимум 20 результатов на запрос без пагинации; при
    достижении потолка truncated равно true.
    """
    has_range = bool(date_from.strip()) or bool(date_to.strip())
    if has_range and not (date_from.strip() and date_to.strip()):
        raise InvalidInput("date_from и date_to задаются только вместе")
    if not name.strip() and not date.strip() and not has_range:
        raise InvalidInput(
            "нужен хотя бы один из аргументов: name, date или диапазон дат"
        )
    for value, field in ((date, "date"), (date_from, "date_from"), (date_to, "date_to")):
        if value.strip() and not _DATE.fullmatch(value.strip()):
            raise InvalidInput(
                f"{field} должен быть в формате DD.MM.YYYY, получено {value!r}"
            )

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
```

Добавить импорт `from datetime import datetime, timedelta` в `server.py`.

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 151.

```bash
git add ttw_mcp/server.py tests/test_server.py
git commit -m "feat: date ranges and row enrichment in tournament search"
```

---

### Task 13: Точные докстринги

**Files:**
- Modify: `ttw_mcp/server.py`, `ttw_mcp/parsers/common.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: ничего нового
- Produces: ничего нового

- [ ] **Step 1: Написать падающий тест**

```python
def test_docstrings_carry_the_measured_gotchas():
    # Докстринг — единственный канал, из которого модель узнаёт об
    # ограничениях источника. Подстрочные проверки тут бесполезны, поэтому
    # сверяемся с формулировками, которые нельзя удовлетворить текстом
    # противоположного смысла.
    player = server.get_player.__doc__
    assert "rated_periods" in player and "не несёт информации" in player
    assert "walkover_win" in player and "walkover_loss" in player
    assert "not_played" in player

    tournament = server.get_tournament.__doc__
    assert "rating_current" in tournament
    assert "rating_at_event" in tournament
    assert "сумма дельт" in tournament

    search = server.search_players.__doc__
    assert "город" in search and "ненадёжно" in search
    assert "несколько профилей" in search
```

- [ ] **Step 2: Запустить, убедиться что падает**

Run: `uv run pytest tests/test_server.py -k measured_gotchas -v`
Expected: FAIL на первом же ассерте

- [ ] **Step 3: Реализация**

Вставить в докстринг `get_player` после абзаца про горизонт истории:

```
    Значение summary["rated_periods"] упирается в 30 и в этой точке не
    несёт информации: это либо честные 29 периодов плюс стартовый, либо
    насыщение при 130. Ниже потолка оно равно len(periods) + 1. Считать
    периоды следует по длине periods.

    Исход матча (result) принимает значения win, loss, walkover_win,
    walkover_loss, not_played и unparsed. Технический результат сайт
    записывает четырьмя способами, по-разному для победившей и
    проигравшей стороны; not_played — счёт 0:0 с нулевой дельтой, матч
    не состоялся и не считается ни победой, ни поражением. Значение
    unparsed означает форму, которой в замерах не встречалось, то есть
    действительно изменившуюся вёрстку.

    Рейтинги приходят с разной точностью: opponent_rating и
    player_rating_at_match дают два знака, best_wins[].player_rating —
    целое, потому что таким его отдаёт сайт. Смешивать их в одном
    расчёте нельзя.
```

Вставить в докстринг `get_tournament`:

```
    Поле rating_current в строках таблицы — это СЕГОДНЯШНИЙ рейтинг
    игрока, а не его рейтинг на день турнира: сайт отдаёт в этой ячейке
    актуальное значение. Разница доходит до двухсот пунктов, поэтому
    средняя сила поля по этому полю не считается. С ratings_at_event=True
    добавляется rating_at_event, восстановленный из профилей участников;
    ratings_at_event_resolved говорит, для скольких строк это удалось.

    Сумма дельт по турниру не равна нулю: во всех десяти разобранных
    турнирах она положительна, от +26.45 до +58.52. Это свойство формулы
    сайта, а не ошибка разбора — искать ошибку у себя не нужно.
```

Заменить в докстринге `search_players` фразу про различение по городу на:

```
    Поле city ненадёжно: встречаются значения вида "--, -Санкт-Петербург",
    "Санкт-Петербург, -Санкт-Петербург" и "--, ЛЕНИНГРАД левая рука".
    Для различения однофамильцев используйте рейтинг и число турниров.

    Один человек может иметь несколько профилей с разными
    идентификаторами — например, отдельный для игры нерабочей рукой, где
    рейтинг втрое ниже. Поле hand показывает пометку, если она есть, но
    связать такие профили сервер не берётся.
```

Вставить в докстринг `get_head_to_head` после абзаца про округление:

```
    Матч без разборчивого счёта приходит с пустыми партиями и исходной
    записью в score_raw. В отличие от get_player, здесь нет поля result,
    поэтому техническую победу от технического поражения можно отличить
    только по score_raw.
```

- [ ] **Step 4: Прогон и коммит**

Run: `uv run pytest -q`
Expected: PASS, 152.

```bash
git add ttw_mcp/server.py ttw_mcp/parsers/common.py tests/test_server.py
git commit -m "docs: put every measured gotcha into the tool docstrings"
```

---

### Task 14: Smoke-проверка и README

**Files:**
- Modify: `tests/test_smoke.py`, `README.md`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: все новые инструменты
- Produces: ничего для последующих задач

- [ ] **Step 1: Дополнить smoke-тест**

```python
def test_live_tournament_matches_still_reconstruct(client):
    # Единственное место, где видно, что состав и матчи разошлись:
    # остальные тесты работают на снимках и останутся зелёными после
    # любого изменения сайта.
    from ttw_mcp import server

    server._client = client
    result = server.get_tournament_matches("6ad412a")
    assert result["participants"] == 17
    assert result["matches"], "матчи собрались хотя бы у части участников"
    assert all(m["date"] == result["date"] for m in result["matches"])
```

Этот тест делает столько же запросов, сколько участников; он помечен
`smoke` и в обычный прогон не входит.

- [ ] **Step 2: Запустить smoke**

Run: `uv run pytest -m smoke -v`
Expected: PASS, 4 теста, около двух минут — семнадцать профилей плюс три
прежние страницы.

- [ ] **Step 3: Обновить README**

В таблицу инструментов добавить `get_tournament_matches` и `get_series`,
отметив, что оба стоят по запросу на участника. В разделе ограничений
заменить упоминание о рейтинге в таблице турнира: `rating_current` —
сегодняшнее значение, `rating_at_event` — восстановленное по флагу.
Добавить строку про исходы матчей и про то, что `not_played` не считается
ни победой, ни поражением.

- [ ] **Step 4: Полный прогон и коммит**

Run: `uv run pytest -q -W error::ResourceWarning`
Expected: PASS, 152, вывод чистый.

```bash
git add tests/test_smoke.py README.md
git commit -m "test: live smoke for tournament match reconstruction, README update"
```
