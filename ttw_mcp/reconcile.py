"""Сведение матчей турнира из профилей его участников.

Страница турнира матчей не содержит — они есть только в профилях
участников, дважды каждый, с обеих сторон. Всё здесь — чистые функции над
уже собранными профилями: ни сети, ни файловой системы, ни знания об
MCP-слое.
"""

from ttw_mcp.errors import ParseError

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


def reconcile_matches(profiles: dict[str, dict], tournament_id: str) -> list[dict]:
    """Сводит матчи одного турнира из профилей участников.

    Отбор идёт по tournament_id, а не по дате: участник мог в тот же день
    сыграть ещё один турнир (get_tournament это отдельно оговаривает), и
    фильтр по дате затянул бы в выдачу матчи чужого турнира того же дня —
    причём не заметно: если у обеих сторон того матча профиль собран,
    записи выглядят обычной зеркальной парой и молча увеличивают число
    матчей турнира, не поднимая никакой ошибки. Замерено, что поле
    tournament_id заполнено у всех проверенных матчей и в дни с двумя
    турнирами делит их начисто.

    Матч виден с двух сторон, если собраны оба профиля, и с одной, если
    собран только один. Строки группируются по паре игроков, и каждой
    ищется зеркальная у соперника. Пары играют дважды за день постоянно —
    групповой этап плюс плей-офф, — поэтому сводятся списки с учётом
    кратности, а не одиночные записи.

    Если у строки нет зеркала, а профиль соперника собран, поднимается
    ParseError: выбрать одну из двух версий счёта молча значило бы отдать
    модели выдуманный результат.

    Вызывающая сторона обязана собирать профили с матчами (include_matches
    по умолчанию и есть True): профиль без ключа matches — это не «у
    игрока не было матчей», а «их не запрашивали», и это не одно и то же.
    Такой профиль в сведение попасть не может по смыслу: молча вернуть по
    нему пустой список значило бы выдать «их не запрашивали» за «их не
    было», поэтому при отсутствии ключа поднимается ParseError.
    """
    rows: dict[tuple[str, str], list[dict]] = {}
    for player_id, profile in profiles.items():
        if "matches" not in profile:
            raise ParseError(
                "get_tournament_matches",
                "matches",
                f"профиль {player_id} собран без матчей (include_matches=False); "
                "reconcile_matches требует профили с матчами",
            )
        for match in profile["matches"]:
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
