"""op.gg 경기 페이지와 세트 정보 읽기.

- 경기: esports.op.gg/matches/<번호>/<slug> 페이지는 경기 정보를 페이지 안 JSON(__NEXT_DATA__)으로 같이 보낸다.
  robots.txt 는 /matches 를 막지 않는다.
- 세트별 진영·선수·챔피언은 그 JSON 에 없고, 페이지가 뜬 뒤 op.gg 화면이 /matches/graphql 의
  GetGameByMatch(matchId, set) 로 불러온다. 같은 쿼리에서 필요한 필드만 골라 세트당 한 번 요청한다
  (op.gg 내부 API 는 이 하나만 쓴다).
"""

import json
import re

import requests

BASE = "https://esports.op.gg"
USER_AGENT = "esports-api/0.1 (research; match metadata)"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
GRAPHQL_URL = f"{BASE}/matches/graphql"
GAME_QUERY = """query GetGameByMatch($matchId: ID!, $set: Int) {
  gameByMatch(matchId: $matchId, set: $set) {
    id
    winner { id }
    teams { side bans team { id acronym } }
    players { side position championId player { nickName } }
  }
}"""
ROLES = {"top": "top", "jun": "jungle", "mid": "mid", "adc": "bot", "sup": "support"}  # op.gg → GamePlayer.role


def match_url(ref: str) -> str:
    """경기 번호나 주소를 받아 페이지 주소로 바꾼다.

    Raises:
        ValueError: 번호도 op.gg 경기 주소도 아님.
    """
    ref = ref.strip()
    if ref.isdigit():
        return f"{BASE}/matches/{ref}"
    if re.match(r"^https://esports\.op\.gg/(?:[a-z]{2}/)?matches/\d+", ref):
        return ref
    raise ValueError(f"op.gg 경기 번호나 주소가 아닙니다: {ref}")


def fetch_match(ref: str, timeout: float = 20) -> tuple[str, dict]:
    """페이지를 받아 (주소, match JSON) 을 돌려준다.

    Raises:
        requests.HTTPError: 페이지 요청 실패.
        ValueError: 페이지에 경기 데이터가 없음.
    """
    url = match_url(ref)
    res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    res.raise_for_status()
    return res.url, parse_match(res.text)


def parse_match(html: str) -> dict:
    """페이지 HTML 에서 match JSON 을 꺼낸다.

    Raises:
        ValueError: __NEXT_DATA__ 나 match 가 없음.
    """
    m = _NEXT_DATA.search(html)
    if not m:
        raise ValueError("페이지에 __NEXT_DATA__ 가 없습니다")
    match = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("match")
    if not match:
        raise ValueError("페이지에 경기 데이터(match)가 없습니다")
    return match


def games_from_videos(match: dict) -> dict[int, dict]:
    """영상 목록에서 세트별 {opgg_game_id, full_video_url, highlight_url} 을 모은다.

    op.gg 는 세트 id 를 영상에 붙여서만 준다. 영상이 없는 세트는 빠진다.
    """
    games: dict[int, dict] = {}
    for v in match.get("videos") or []:
        g = v.get("game") or {}
        if not g.get("set"):
            continue
        row = games.setdefault(int(g["set"]), {"opgg_game_id": int(g["id"]), "full_video_url": "",
                                               "highlight_url": ""})
        if v.get("type") == "full-game":
            row["full_video_url"] = v.get("url") or ""
        elif v.get("type") == "highlights":
            row["highlight_url"] = v.get("url") or ""
    return games


def fetch_game(match_id: int | str, set_number: int, timeout: float = 10) -> dict | None:
    """세트 하나의 gameByMatch JSON. 열리지 않은 세트(3:1 로 끝난 BO5 의 5세트 등)는 None.

    Raises:
        requests.HTTPError: 요청 실패.
        ValueError: GraphQL 오류 응답.
    """
    res = requests.post(
        GRAPHQL_URL, timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Referer": f"{BASE}/matches/{match_id}"},
        json={"operationName": "GetGameByMatch", "query": GAME_QUERY,
              "variables": {"matchId": str(match_id), "set": set_number}})
    res.raise_for_status()
    body = res.json()
    if body.get("errors"):
        raise ValueError(f"op.gg 세트 조회 오류: {body['errors'][0].get('message')}")
    return (body.get("data") or {}).get("gameByMatch")


def parse_game(game: dict) -> dict:
    """gameByMatch JSON → {opgg_game_id, winner: 팀 op.gg id | None, sides: {진영: 팀 op.gg id},
    bans: {진영: [챔피언 번호]}, players: [{side, role, name, champion_id}]}. 모르는 포지션의 선수는 빠진다."""
    teams = [t for t in game.get("teams") or [] if t.get("side") in ("blue", "red")]
    players = [{"side": p["side"], "role": ROLES[p.get("position")], "name": (p.get("player") or {}).get("nickName") or "",
                "champion_id": str(p.get("championId") or "")}
               for p in game.get("players") or [] if p.get("side") in ("blue", "red") and p.get("position") in ROLES]
    winner = (game.get("winner") or {}).get("id")
    return {"opgg_game_id": int(game["id"]), "winner": int(winner) if winner else None,
            "sides": {t["side"]: int(t["team"]["id"]) for t in teams if (t.get("team") or {}).get("id")},
            "bans": {t["side"]: [str(b) for b in t.get("bans") or []] for t in teams},
            "players": players}
