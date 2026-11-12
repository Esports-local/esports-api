"""op.gg 경기 페이지 읽기.

esports.op.gg/matches/<번호>/<slug> 페이지는 경기 정보를 페이지 안 JSON(__NEXT_DATA__)으로 같이 보낸다.
그 JSON 만 읽는다 (op.gg 내부 API 는 쓰지 않음). robots.txt 는 /matches 를 막지 않는다.
세트별 진영·선수·챔피언은 이 JSON 에 없다.
"""

import json
import re

import requests

BASE = "https://esports.op.gg"
USER_AGENT = "esports-api/0.1 (research; match metadata)"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


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
