"""op.gg 세트 정보(GetGameByMatch) → 세트별 블루/레드 팀·승자·밴, GamePlayer(진영·포지션·선수·챔피언).

import_match 명령과 영상 등록(POST /games)이 같이 쓴다. 저장한 세트에 붙은 영상의 헤더도 다시 만든다.
"""

from django.db import transaction

from matches import ddragon, opgg
from matches.header import refresh_header
from matches.models import GamePlayer, Match, MatchGame


def import_lineups(match: Match) -> int:
    """1세트부터 best_of 까지 op.gg 세트 정보를 받아 저장한다. 저장한 세트 수.

    Raises:
        requests.RequestException, ValueError: op.gg·Data Dragon 요청 실패.
    """
    champs = None
    saved = []
    for number in range(1, match.best_of + 1):
        game = opgg.fetch_game(match.opgg_id, number)
        if not game:
            continue
        if champs is None:  # 열린 세트가 있을 때만 받는다
            champs = ddragon.champions(ddragon.version_for(match.patch))
        saved.append(save_lineup(match, number, opgg.parse_game(game), champs))
    for game in saved:  # 이전 세트(피어리스)가 바뀌면 뒤 세트 헤더도 바뀐다
        for video in game.videos.all():
            refresh_header(video)
    return len(saved)


@transaction.atomic
def save_lineup(match: Match, number: int, g: dict, champs: dict[str, dict]) -> MatchGame:
    """opgg.parse_game 결과로 세트(블루/레드 팀·승자·밴)와 GamePlayer 를 저장한다. 선수 name_ko 는 안 건드린다."""
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
        c = champs.get(p["champion_id"], {})
        GamePlayer.objects.update_or_create(
            game=game, side=p["side"], role=p["role"],
            defaults={"name": p["name"], "champion": c.get("name", ""), "champion_ko": c.get("ko", "")})
    return game
