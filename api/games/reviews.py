"""해설 대사 사람 검수 (LineReview): /lines 응답에 붙이고, 번역할 때 고친 문장을 analyzer 에 넘긴다."""

from matches.models import GameVideo, LineReview


def current(v: GameVideo, lines: list[dict]) -> dict[int, LineReview]:
    """{대사 id: 검수}. 검수한 뒤 ASR 원문이 바뀐 대사(asr 다시 실행)는 빠진다."""
    asr = {line["id"]: line["text"] for line in lines}
    return {r.line_id: r for r in v.reviews.all() if asr.get(r.line_id) == r.asr_text}


def as_json(r: LineReview | None) -> dict | None:
    if r is None:
        return None
    return {"text": r.text or None, "reviewed": r.reviewed, "updated_at": r.updated_at.isoformat()}


def text_overrides(v: GameVideo) -> dict[str, str]:
    """번역에 쓸 고친 문장 {대사 id(문자열): 문장}. asr 결과가 없으면 빈 dict."""
    lines = ((v.results.get("asr") or {}).get("result") or {}).get("lines") or []
    return {str(i): r.text for i, r in current(v, lines).items() if r.text}
