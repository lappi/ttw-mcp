"""Сбор нескольких профилей для многозапросных инструментов.

Сайт отвечает за 4–17 секунд и просит себя не обходить, поэтому запросы
идут строго последовательно, а один идентификатор запрашивается один раз
за вызов. Между вызовами ничего не хранится: состояния на диске у сервера
нет по устройству.
"""

from collections.abc import Iterable

from ttw_mcp.errors import NotFound, UpstreamError
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

    В `missing` попадают только отсутствующие (`NotFound`) и временно
    недоступные (`UpstreamError`) игроки. Поломка разбора (`ParseError`)
    не скрывается за этим списком и уходит наружу: это не потеря одного
    игрока, а системная поломка парсера, которая при смене вёрстки сайта
    заденет каждый профиль сразу, и молчать о ней нельзя.
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
        except (NotFound, UpstreamError):
            missing.append(player_id)
    return profiles, missing
