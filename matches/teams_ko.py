"""팀 이름 사전 (코드로 관리): op.gg 팀 약칭 → 한국어 해설 표기. 숏폼 자막과 받아쓰기 교정에 쓴다.

새 팀은 여기에 한 줄 추가한다. 대소문자는 가리지 않는다. 없는 팀은 약칭 그대로 쓴다.
"""

TEAMS_KO = {
    "T1": "T1", "GEN": "젠지", "HLE": "한화생명", "KT": "KT", "DK": "디플러스 기아", "NS": "농심",
    "BFX": "BNK 피어엑스", "DRX": "DRX", "DNF": "DN 프릭스", "BRO": "브리온",
    "BLG": "BLG", "JDG": "JDG", "TES": "TES", "AL": "AL", "WBG": "WBG",
}


def team_ko(acronym: str | None) -> str | None:
    if not acronym:
        return acronym
    return {k.lower(): v for k, v in TEAMS_KO.items()}.get(acronym.lower(), acronym)
