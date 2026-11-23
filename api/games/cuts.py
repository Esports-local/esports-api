"""장면 전환 사람 검수 (CutReview): 컷 탭에서 전환마다 통과·불통을 저장한다 (스펙 19·20번)."""

from matches.models import CutReview, GameVideo

SAME_SEC = 0.05


def transitions(v: GameVideo) -> list[dict]:
    """segments 단계의 전환 목록 (없으면 빈 목록)."""
    return (((v.results or {}).get("segments") or {}).get("result") or {}).get("transitions") or []


def current(v: GameVideo, trans: list[dict]) -> dict[int, CutReview]:
    """{전환 id: 검수}. segments 를 다시 돌려 시각·종류가 바뀐 전환의 검수는 빠진다."""
    by_id = {t["id"]: t for t in trans}
    out = {}
    for r in v.cut_reviews.all():
        t = by_id.get(r.transition_id)
        if t and t["kind"] == r.kind and abs(t["start_sec"] - r.start_sec) <= SAME_SEC:
            out[r.transition_id] = r
    return out


def summary(trans: list[dict], reviews: dict[int, CutReview]) -> dict:
    n_pass = sum(r.verdict == CutReview.Verdict.PASS for r in reviews.values())
    n_fail = sum(r.verdict == CutReview.Verdict.FAIL for r in reviews.values())
    return {"total": len(trans), "pass": n_pass, "fail": n_fail, "unchecked": len(trans) - n_pass - n_fail}


def as_json(r: CutReview) -> dict:
    return {"transition_id": r.transition_id, "verdict": r.verdict, "updated_at": r.updated_at.isoformat()}
