"""Riot Data Dragon: 챔피언 번호·이름 → 영어·한국어 이름, 스킬 이름.

op.gg 세트 정보는 챔피언을 번호(championId, 예: 78)로만 준다. Data Dragon champion.json 의 key 가 그 번호다.
버전은 경기 패치(Match.patch)와 같은 것을 쓰고, 없으면 같은 시즌·패치(앞 두 자리)의 버전, 그것도 없으면 최신.
같은 버전 데이터는 프로세스 안에서 한 번만 받고, 버전 목록은 한 시간 동안 다시 받지 않는다 (실패는 기억하지 않음).
"""

import time
from functools import lru_cache

import requests

BASE = "https://ddragon.leagueoflegends.com"
TIMEOUT = 5  # 영상 등록 요청 안에서도 불리므로 짧게
VERSIONS_TTL = 3600
_versions: tuple[float, list[str]] = (0.0, [])


def _get(path: str):
    res = requests.get(f"{BASE}{path}", timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def pick_version(versions: list[str], patch: str) -> str:
    """Data Dragon 버전 목록(최신순)에서 경기 패치에 맞는 버전을 고른다.

    Raises:
        ValueError: 버전 목록이 비어 있음.
    """
    if not versions:
        raise ValueError("Data Dragon 버전 목록이 비어 있습니다")
    if patch in versions:
        return patch
    head = ".".join(patch.split(".")[:2])
    return next((v for v in versions if head and v.startswith(head + ".")), versions[0])


def version_for(patch: str) -> str:
    """경기 패치에 맞는 Data Dragon 버전. Raises: requests.RequestException, ValueError."""
    global _versions
    fetched_at, versions = _versions
    if not versions or time.monotonic() - fetched_at > VERSIONS_TTL:
        versions = _get("/api/versions.json")
        _versions = (time.monotonic(), versions)
    return pick_version(versions, patch or "")


@lru_cache(maxsize=8)
def champions(version: str) -> dict[str, dict]:
    """{"78": {"id": "Poppy", "name": "Poppy", "ko": "뽀삐"}, …}. id 는 Data Dragon 파일 이름.

    Raises:
        requests.RequestException: 요청 실패.
    """
    names: dict[str, dict] = {}
    for lang, field in (("en_US", "name"), ("ko_KR", "ko")):
        for c in _get(f"/cdn/{version}/data/{lang}/champion.json")["data"].values():
            names.setdefault(c["key"], {"id": c["id"]})[field] = c["name"]
    return names


def by_name(version: str) -> dict[str, dict]:
    """영어 이름(GamePlayer.champion) → {"id", "name", "ko"}."""
    return {c["name"]: c for c in champions(version).values()}


@lru_cache(maxsize=256)
def skills(version: str, champion_id: str) -> dict[str, str]:
    """한국어 스킬 이름 {"P": 패시브, "Q", "W", "E", "R"}. champion_id 는 Data Dragon id (예: LeeSin).

    Raises:
        requests.RequestException: 요청 실패.
    """
    d = _get(f"/cdn/{version}/data/ko_KR/champion/{champion_id}.json")["data"][champion_id]
    return {"P": d["passive"]["name"], **{k: s["name"] for k, s in zip("QWER", d["spells"])}}
