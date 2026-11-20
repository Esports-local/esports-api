"""op.gg 세트 정보(GetGameByMatch) → 세트별 블루/레드 팀·승자·밴, GamePlayer(진영·포지션·선수·챔피언).

import_match 명령과 영상 등록(POST /games)이 같이 쓴다. 저장한 세트와 그 뒤 세트에 붙은 영상의 헤더도 다시 만든다.
세트 하나의 응답이 이상하면(키 없음, 세트 id 겹침) 그 세트만 건너뛴다.
"""

import logging

import requests
from django.db import IntegrityError, transaction

from matches import ddragon, opgg
from matches.header import refresh_match_headers
from matches.models import GamePlayer, Match, MatchGame

log = logging.getLogger(__name__)
# 호출하는 쪽(영상 등록·import_match)이 잡아서 경고로 남길 오류
LINEUP_ERRORS = (requests.RequestException, OSError, ValueError, KeyError, IndexError, TypeError, IntegrityError)


def import_lineups(match: Match) -> int:
    """1세트부터 best_of 까지 op.gg 세트 정보를 받아 저장한다. 저장한 세트 수.

    Raises:
        LINEUP_ERRORS 중 하나: op.gg·Data Dragon 요청 실패 (세트 하나의 응답 오류는 건너뜀).
    """
    champs = None
    saved: list[MatchGame] = []
    for number in range(1, match.best_of + 1):
        game = opgg.fetch_game(match.opgg_id, number)
        if not game:
            continue
        if champs is None:  # 열린 세트가 있을 때만 받는다
            champs = ddragon.champions(ddragon.version_for(match.patch))
        try:
            saved.append(save_lineup(match, number, opgg.parse_game(game), champs))
        except (KeyError, TypeError, ValueError, IntegrityError) as e:
            log.warning("op.gg %s %d세트 정보를 저장하지 못했습니다: %r", match.opgg_id, number, e)
    if saved:
        refresh_match_headers(min(saved, key=lambda g: g.number))
    return len(saved)


@transaction.atomic
def save_lineup(match: Match, number: int, g: dict, champs: dict[str, dict]) -> MatchGame:
    """opgg.parse_game 결과로 세트(블루/레드 팀·승자·밴)와 GamePlayer 를 저장한다.

    선수 name_ko 는 안 건드리고, 번호를 모르는 챔피언은 기존 값을 지우지 않는다.
    """
    teams = {t.opgg_id: t for t in (match.home_team, match.away_team)}
    name = lambda cid: champs.get(cid, {}).get("name", "")  # noqa: E731
    defaults = {"opgg_game_id": g["opgg_game_id"],
                "bans": {side: [name(c) for c in ids if name(c)] for side, ids in g["bans"].items()}}
    blue, red = teams.get(g["sides"].get("blue")), teams.get(g["sides"].get("red"))
    if blue and red and blue != red:
        defaults.update(blue_team=blue, red_team=red)
    if teams.get(g.get("winner")):
        defaults["winner"] = teams[g["winner"]]
    game, _ = MatchGame.objects.update_or_create(match=match, number=number, defaults=defaults)
    for p in g["players"]:
        row = {"name": p["name"]}
        if c := champs.get(p["champion_id"]):
            row.update(champion=c.get("name", ""), champion_ko=c.get("ko", ""))
        GamePlayer.objects.update_or_create(game=game, side=p["side"], role=p["role"], defaults=row)
    return game
