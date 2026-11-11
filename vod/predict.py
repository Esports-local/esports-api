"""예측 실행.

지금은 mock 만 있다 (LLM 연동 전). PREDICT_BACKEND=mock 이면 요청 즉시 결과를 채워
ui 가 done 화면까지 개발할 수 있게 한다. 실제 LLM 은 1차(header) → body 선별 → 2차(예측 + 근거) 순서로 붙인다.
"""

from django.conf import settings

from vod.models import Episode, JobStatus, Prediction


def run(prediction: Prediction) -> None:
    """예측을 실행해 prediction 을 갱신한다."""
    backend = settings.PREDICT_BACKEND
    if backend == "mock":
        _run_mock(prediction)
    else:  # LLM 백엔드는 아직 없음 → queued 로 남긴다
        return


def _first_scene(ep: Episode) -> dict | None:
    """분석 결과의 첫 장면 (근거 예시용)."""
    scenes = (ep.analysis or {}).get("scenes") or []
    return scenes[0] if scenes else None


def _run_mock(p: Prediction) -> None:
    episodes = list(p.series.episodes.filter(number__lt=p.target).order_by("number"))
    characters = list(p.series.characters.values_list("id", flat=True)[:2])
    evidence = []
    for ep in episodes[-2:]:
        s = _first_scene(ep)
        if s:
            evidence.append({
                "episode_id": ep.id, "scene_id": s.get("id", 1),
                "start": s.get("start_sec", 0.0), "end": s.get("end_sec", 0.0),
                "note": s.get("summary") or f"{ep.number}화 첫 장면",
            })
    p.items = [{
        "id": 1,
        "text": f"(mock) {p.target}화에서 주요 인물 사이의 갈등이 드러날 가능성이 높다",
        "category": "conflict",
        "characters": characters,
        "confidence": 0.5,
        "evidence": evidence,
        "counter_evidence": [],
    }]
    p.status = JobStatus.DONE
    p.error = ""
    p.save(update_fields=["items", "status", "error", "updated_at"])
