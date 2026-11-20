"""세트 영상 헤더: 숏폼·자막 교정 때 그 경기에서 기본으로 알아야 하는 정보. 사람·LLM 입력 없이 자동으로 만든다.

출처는 op.gg(경기·세트·선수·챔피언·밴·승자)와 Riot Data Dragon(챔피언 한국어 이름·스킬 이름) 뿐이다.
피어리스 드래프트(하드): 앞 세트에서 양 팀이 고른 챔피언은 이 세트에서 아무도 고를 수 없다. 밴은 넘어가지 않는다.
FEARLESS_LEAGUES 의 FEARLESS_SINCE 년 이후 경기에만 적용한다 (그 밖에는 series.fearless=false, 목록은 빈 칸).

    {"match": {...}, "teams": {"blue": {...}, "red": {...}}, "players": [...], "bans": {...},
     "series": {"score_before": {...}, "previous": [...], "fearless_unavailable": [...]}, "source": {...}}
"""

import logging

import requests
from django.utils import timezone

from matches import ddragon
from matches.models import GameVideo, MatchGame

log = logging.getLogger(__name__)
ROLE_ORDER = ["top", "jungle", "mid", "bot", "support"]
FEARLESS_LEAGUES = {"LCK", "LPL", "MSI", "Worlds"}  # Match.league (op.gg league shortName)
FEARLESS_SINCE = 2025


def is_fearless(m) -> bool:
    return m.league in FEARLESS_LEAGUES and (m.year or 0) >= FEARLESS_SINCE


def _champ(names: dict, name: str) -> dict:
    c = names.get(name) or {}
    return {"name": name, "ko": c.get("ko") or ""}


def _picks(game: MatchGame, names: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"blue": [], "red": []}
    for p in sorted(game.players.all(), key=lambda p: ROLE_ORDER.index(p.role) if p.role in ROLE_ORDER else 9):
        if p.champion:
            out[p.side].append(_champ(names, p.champion))
    return out


def _acr(team) -> str | None:
    return team.acronym if team else None


def build_header(game: MatchGame) -> dict:
    """세트 하나의 헤더. 선수가 없으면(op.gg 세트 정보를 못 받음) 빈 dict.

    Raises:
        requests.RequestException: Data Dragon 요청 실패.
    """
    players = sorted(game.players.all(), key=lambda p: (p.side != "blue", ROLE_ORDER.index(p.role)
                                                        if p.role in ROLE_ORDER else 9))
    if not players:
        return {}
    m = game.match
    version = ddragon.version_for(m.patch)
    names = ddragon.by_name(version)
    side_team = {"blue": game.blue_team, "red": game.red_team}

    def player(p) -> dict:
        c = names.get(p.champion) or {}
        champ = {**_champ(names, p.champion), "skills": ddragon.skills(version, c["id"]) if c else {}}
        return {"side": p.side, "team": _acr(side_team[p.side]), "role": p.role, "name": p.name, "champion": champ}

    previous = list(m.games.filter(number__lt=game.number).select_related("blue_team", "red_team", "winner")
                    .prefetch_related("players").order_by("number"))
    score = {t.acronym: 0 for t in (m.home_team, m.away_team)}
    fearless = is_fearless(m)
    unavailable = []
    prev_out = []
    for g in previous:
        if g.winner:
            score[g.winner.acronym] = score.get(g.winner.acronym, 0) + 1
        picks = _picks(g, names)
        teams = {"blue": _acr(g.blue_team), "red": _acr(g.red_team)}
        prev_out.append({"set": g.number, "blue": teams["blue"], "red": teams["red"], "winner": _acr(g.winner),
                         "picks": picks, "bans": {s: [_champ(names, n) for n in b] for s, b in g.bans.items()}})
        if fearless:
            unavailable += [{**c, "set": g.number, "team": teams[side]} for side, cs in picks.items() for c in cs]

    return {
        "match": {"opgg_id": m.opgg_id, "name": m.name, "league": m.league, "stage": m.stage, "year": m.year,
                  "format": f"BO{m.best_of}", "set": game.number, "patch": m.patch},
        "teams": {side: {"name": t.acronym, "full": t.name} if t else None for side, t in side_team.items()},
        "players": [player(p) for p in players],
        "bans": {s: [_champ(names, n) for n in b] for s, b in game.bans.items()},
        "series": {"score_before": score, "previous": prev_out, "fearless": fearless,
                   "fearless_unavailable": unavailable},
        "source": {"opgg": m.source_url, "ddragon_version": version, "built_at": timezone.now().isoformat()},
    }


def refresh_header(video: GameVideo) -> GameVideo:
    """영상의 헤더를 다시 만들어 저장한다. 세트가 없으면 비우고, Data Dragon 이 안 되면 이전 헤더를 둔다."""
    try:
        header = build_header(video.game) if video.game_id else {}
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("헤더를 만들지 못했습니다 (%s): %s", video.work_name, e)
        return video
    video.header = header
    video.save(update_fields=["header"])
    return video


def refresh_match_headers(game: MatchGame) -> None:
    """이 세트와 뒤 세트에 붙은 영상의 헤더를 다시 만든다 (뒤 세트 헤더에 앞 세트 밴픽·스코어가 들어가므로)."""
    for video in GameVideo.objects.filter(game__match_id=game.match_id, game__number__gte=game.number) \
            .select_related("game__match"):
        refresh_header(video)
