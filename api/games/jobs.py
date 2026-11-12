"""세트 영상 분석: analyzer 에 작업을 맡기고, 끝나면 결과를 가져온다."""

import time

from api.exceptions import ApiError
from api.games import analyzer, reviews
from matches.models import AnalyzeStatus, GameVideo
from matches.outputs import save_video, work_dir

DEFAULT_STAGES = ["preprocess", "roi_ocr", "asr"]


def source_for(v: GameVideo) -> str:
    """영상의 원본 파일 이름. 비어 있으면 analyzer 영상 목록에서 work_name 과 이름이 같은 파일을 찾는다.

    Raises:
        ApiError: 원본 영상을 찾지 못함 (404).
    """
    if v.video_name:
        return v.video_name
    for s in analyzer.list_videos():
        if s["name"].rsplit(".", 1)[0] == v.work_name:
            v.video_name = s["name"]
            v.save(update_fields=["video_name"])
            return v.video_name
    raise ApiError("원본 영상을 찾을 수 없습니다", 404)


def start(v: GameVideo, stages: list[str], params: dict | None = None) -> GameVideo:
    """analyzer 작업을 시작하고 영상 상태를 running 으로 바꾼다.

    Raises:
        ApiError: 이미 분석 중(409), analyzer 오류.
    """
    if v.analyze_status == AnalyzeStatus.RUNNING:
        raise ApiError("이미 분석 중입니다", 409)
    name = source_for(v)
    source = next((s for s in analyzer.list_videos() if s["name"] == name), None)
    if source is None or not source["selectable"]:
        raise ApiError(f"분석할 수 없는 영상입니다: {(source or {}).get('reason') or name}")
    if "translate" in stages:  # 사람이 고친 대사는 ASR 원문 대신 고친 문장으로 번역한다
        overrides = reviews.text_overrides(v)
        if overrides:
            params = {**(params or {})}
            params["translate"] = {**params.get("translate", {}), "text_overrides": overrides}
    job_id = f"game{v.id}-{int(time.time())}"
    analyzer.start_job(job_id, name, stages, params)
    v.job_id, v.error, v.analyze_status = job_id, "", AnalyzeStatus.RUNNING
    v.save(update_fields=["job_id", "error", "analyze_status", "updated_at"])
    return v


def refresh(v: GameVideo) -> dict | None:
    """분석 중이면 analyzer 에 상태를 묻고, 끝났으면 결과를 가져온다. 진행 상태(job)를 돌려준다.

    analyzer 에 연결이 안 되면 상태를 그대로 둔다.
    """
    if v.analyze_status != AnalyzeStatus.RUNNING or not v.job_id:
        return None
    try:
        job = analyzer.get_job(v.job_id)
    except ApiError as e:
        if e.status == 404:  # analyzer 를 다시 띄워 작업 기록이 없어짐
            _finish(v, "analyzer 가 다시 시작되어 작업 기록이 없어졌습니다")
        return None
    if job["status"] in ("queued", "running"):
        return job
    if job["status"] == "succeeded":
        _finish(v, "")
    else:
        _finish(v, job.get("error") or ("중지됨" if job["status"] == "cancelled" else "실패"))
    return job


def _finish(v: GameVideo, error: str) -> None:
    """결과 폴더를 다시 읽어 저장한다. error 가 있으면 failed."""
    saved = save_video(work_dir(v.work_name), v.work_name, v.title, v.language, v.game, video_name=v.video_name)
    if error:
        saved.analyze_status, saved.error = AnalyzeStatus.FAILED, error
        saved.save(update_fields=["analyze_status", "error"])
    v.refresh_from_db()
