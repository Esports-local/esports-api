"""analyzer HTTP 호출 (settings.MAIN_URL). 연동 스펙은 esports-analyzer/app/schemas.py."""

import requests
from django.conf import settings

from api.exceptions import ApiError


def _call(method: str, path: str, timeout: float = 30, **kwargs):
    url = settings.MAIN_URL.rstrip("/") + path
    try:
        res = requests.request(method, url, timeout=timeout, **kwargs)
    except requests.RequestException as e:
        raise ApiError(f"analyzer 에 연결하지 못했습니다 ({settings.MAIN_URL})", 502) from e
    if res.status_code >= 400:
        try:
            detail = res.json().get("detail")
        except ValueError:
            detail = None
        raise ApiError(detail if isinstance(detail, str) else f"analyzer 오류 ({res.status_code})",
                       res.status_code if res.status_code in (400, 404, 409) else 502)
    return res.json()


def list_videos() -> list[dict]:
    """GET /videos — [{name, size_bytes, duration_sec, width, height, has_audio, selectable, reason}]"""
    return _call("GET", "/videos", timeout=120)


def start_job(job_id: str, video: str, stages: list[str], params: dict | None = None) -> dict:
    """POST /jobs — 다른 작업이 돌고 있으면 ApiError 409."""
    return _call("POST", "/jobs", json={"job_id": job_id, "video": video, "stages": stages, "params": params or {}})


def get_job(job_id: str) -> dict:
    """GET /jobs/{id} — {status: queued|running|succeeded|failed|cancelled, current_stage, elapsed_sec, error}"""
    return _call("GET", f"/jobs/{job_id}")


def cancel_job(job_id: str) -> dict:
    return _call("POST", f"/jobs/{job_id}/cancel")


def estimate(video: str, conditions: list[str]) -> dict:
    """POST /estimate — {model, lines, requests, input_tokens: {조건: 토큰}}"""
    return _call("POST", "/estimate", json={"video": video, "conditions": conditions}, timeout=600)
