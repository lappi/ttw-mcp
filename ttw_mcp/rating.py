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

    Проходит и по matches, и по best_wins — лучшие победы это тоже матчи,
    из того же блока страницы, и у них та же беда: сайт пишет в строке
    player_rating_current (сегодняшний рейтинг игрока), а не значение на
    момент той победы. Кэш по дате общий для обоих списков. Любого списка
    может не быть вовсе при include_matches=False, поэтому оба читаются
    через profile.get(...).
    """
    cache: dict[str, float | None] = {}

    def _rating_on(date: str) -> float | None:
        if date not in cache:
            cache[date] = rating_at_event(profile, date)
        return cache[date]

    for match in profile.get("matches", []):
        match["player_rating_at_match"] = _rating_on(match["date"])
    for win in profile.get("best_wins", []):
        win["player_rating_at_match"] = _rating_on(win["date"])
