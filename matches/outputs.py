"""analyzer 결과 폴더(outputs/<이름>/work/*.json)를 GameVideo 로 저장한다. 가공하지 않고 그대로 넣는다."""

import json
import os
from pathlib import Path

from django.db import transaction

from matches.models import AnalyzeStatus, GameVideo

STAGES = ["header", "preprocess", "segments", "roi_ocr", "asr", "translate", "timeline", "evaluate"]
OUTPUTS_ROOT = Path(os.environ.get("ANALYZER_OUTPUTS_IN_CONTAINER", "/outputs"))


def work_dir(work_name: str) -> Path:
    return OUTPUTS_ROOT / work_name / "work"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@transaction.atomic
def save_video(work: Path, work_name: str, title: str, lang: str, **extra) -> GameVideo:
    """결과 JSON 을 모두 읽어 저장한다 (같은 work_name 은 덮어씀). extra 는 GameVideo 필드 (video_name 등).

    header.json 은 GameVideo.header 에도 넣는다. analyzer 가 op.gg 에서 못 받았으면(error) 이전 헤더를 둔다.
    """
    results = {s: d for s in STAGES if (d := _read(work / f"{s}.json")) is not None}
    pre = (results.get("preprocess") or {}).get("result") or {}
    header = (results.get("header") or {}).get("result") or {}
    if header and not header.get("error"):
        extra["header"] = header
    video, _ = GameVideo.objects.update_or_create(
        work_name=work_name,
        defaults={"title": title, "language": lang, "duration": pre.get("duration_sec"),
                  "run_log": _read(work / "run_log.json") or [], "results": results,
                  "analyze_status": AnalyzeStatus.DONE if results else AnalyzeStatus.PENDING, **extra})
    return video
