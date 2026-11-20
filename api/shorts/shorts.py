"""숏폼: 이벤트 → 구간 계산, 같은 요청 판별(key), analyzer 렌더 맡기기·상태 갱신·저장소 업로드.

흐름
1. POST /games/{id}/shorts → 구간·자막·제목으로 key(입력 해시)를 만든다
   - 같은 key 가 있으면 그 숏폼을 돌려준다 (done 이면 렌더 없이 바로, failed 면 다시 맡김)
   - 없으면 Short 를 만들고 analyzer POST /shorts 로 맡긴다 (analyzer 가 줄을 세움)
2. GET /shorts/{id} → 끝나지 않았으면 analyzer 에 상태를 묻는다
   - succeeded: analyzer 결과 폴더(/outputs, 읽기 전용 마운트)의 mp4 를 저장소 shorts/<key>.mp4 로 올리고 done
   - analyzer 를 다시 띄워 기록이 없으면(404) 같은 내용으로 다시 맡긴다 (결과 파일이 있으면 analyzer 가 바로 succeeded)
"""

import hashlib
import json

from django.db import IntegrityError, transaction
from django.utils import timezone

from api.exceptions import ApiError
from api.games import analyzer, jobs, reviews
from config import storage
from matches.models import GameVideo, Short, ShortStatus
from matches.outputs import OUTPUTS_ROOT

EVENT_TYPES = ("kill", "tower", "objective")
SUBTITLES = ("ko", "en", "none")
PRE_SEC, POST_SEC, MAX_PAD = 6.0, 4.0, 15.0
MAX_EVENTS = 5
TYPE_LABEL = {"kill": "킬", "tower": "타워", "objective": "오브젝트"}


def events(v: GameVideo) -> list[dict]:
    """timeline 이벤트 + 숏폼 기본 구간(clip). timeline 결과가 없으면 404."""
    data = v.results.get("timeline")
    if not data:
        raise ApiError("timeline 결과가 없습니다", 404)
    return [{**e, "clip": clip(e, v.duration, PRE_SEC, POST_SEC)} for e in data["result"]["events"]]


def clip(e: dict, duration: float | None, pre: float, post: float) -> dict:
    """이벤트 하나의 구간: start_sec - pre ~ end_sec + post, 영상 범위 안으로."""
    start = max(0.0, e["start_sec"] - pre)
    end = e["end_sec"] + post
    if duration:
        end = min(end, duration)
    return {"start_sec": round(start, 2), "end_sec": round(end, 2)}


def merge(spans: list[dict]) -> list[dict]:
    """시간순으로 정렬하고 겹치거나 맞닿은 구간을 합친다."""
    out: list[dict] = []
    for s in sorted(spans, key=lambda x: x["start_sec"]):
        if out and s["start_sec"] <= out[-1]["end_sec"]:
            out[-1]["end_sec"] = max(out[-1]["end_sec"], s["end_sec"])
        else:
            out.append(dict(s))
    return out


def title_for(v: GameVideo, picked: list[dict]) -> str:
    """화면 위 제목: "T1 vs BLG · Doran 킬" / 여러 개면 "T1 vs BLG · 킬 2, 타워 1"."""
    teams = v.results.get("timeline", {}).get("result", {}).get("teams", {})
    head = f"{teams['blue']} vs {teams['red']}" if teams.get("blue") and teams.get("red") else v.title
    if len(picked) == 1:
        e = picked[0]
        who = (e.get("players", {}).get("killer") or [e.get("team_name") or ""])[0]
        return f"{head} · {who} {TYPE_LABEL[e['type']]}".strip()
    counts = {}
    for e in picked:
        counts[TYPE_LABEL[e["type"]]] = counts.get(TYPE_LABEL[e["type"]], 0) + 1
    return f"{head} · " + ", ".join(f"{k} {n}" for k, n in counts.items())


def subtitle_lines(v: GameVideo, mode: str, segments: list[dict]) -> list[dict]:
    """구간에 걸친 대사 [{start_sec, end_sec, text}]. ko 는 검수로 고친 문장 우선, en 은 번역 조건 B."""
    if mode == "none":
        return []
    lines = (v.results.get("asr") or {}).get("result", {}).get("lines", [])
    if mode == "ko":
        fixed = reviews.text_overrides(v)
        texts = {ln["id"]: fixed.get(str(ln["id"]), ln["text"]) for ln in lines}
    else:
        tr = (v.results.get("translate") or {}).get("result", {}).get("lines", {})
        if not tr:
            raise ApiError("번역 결과가 없습니다 (en 자막은 translate 단계 뒤에 만들 수 있습니다)")
        texts = {ln["id"]: (tr.get(str(ln["id"])) or {}).get("B") or "" for ln in lines}
    return [{"start_sec": ln["start_sec"], "end_sec": ln["end_sec"], "text": texts[ln["id"]]}
            for ln in lines if texts[ln["id"]] and any(
                ln["end_sec"] > s["start_sec"] and ln["start_sec"] < s["end_sec"] for s in segments)]


def make_key(v: GameVideo, segments: list[dict], subs: list[dict], title: str) -> str:
    """같은 입력이면 같은 key. timeline 을 다시 돌리면(created_at 이 바뀜) 다른 key."""
    version = (v.results.get("timeline") or {}).get("created_at", "")
    raw = json.dumps({"work": v.work_name, "version": version, "segments": segments, "subs": subs, "title": title},
                     ensure_ascii=False, sort_keys=True)
    return "s" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def request(v: GameVideo, event_ids: list[int], mode: str, pre: float, post: float) -> tuple[Short, bool]:
    """숏폼을 요청한다. (숏폼, 새로 만들었는지).

    Raises:
        ApiError: 잘못된 입력(400), timeline 없음(404), analyzer 연결 실패(502).
    """
    by_id = {e["id"]: e for e in events(v)}
    missing = [i for i in event_ids if i not in by_id]
    if missing:
        raise ApiError(f"없는 이벤트입니다: {missing[0]}")
    picked = sorted((by_id[i] for i in event_ids), key=lambda e: e["start_sec"])
    segments = merge([clip(e, v.duration, pre, post) for e in picked])
    subs = subtitle_lines(v, mode, segments)
    title = title_for(v, picked)
    key = make_key(v, segments, subs, title)

    short = Short.objects.filter(key=key).first()
    created = short is None
    if created:
        try:
            with transaction.atomic():
                short = Short.objects.create(video=v, key=key, event_ids=sorted(event_ids), segments=segments,
                                             subtitles=mode, title=title)
        except IntegrityError:  # 같은 요청이 동시에 들어옴
            short, created = Short.objects.get(key=key), False
    if created or short.status == ShortStatus.FAILED:
        _submit(short, subs)
    return short, created


def _submit(short: Short, subs: list[dict] | None = None) -> None:
    """analyzer 에 렌더를 맡긴다 (시도 횟수 +1). analyzer 오류는 failed 로 남기고 다시 던진다."""
    v = short.video
    if subs is None:
        subs = subtitle_lines(v, short.subtitles, short.segments)
    short.attempts += 1
    short.status, short.error, short.finished_at = ShortStatus.QUEUED, "", None
    try:
        state = analyzer.create_short(short.key, jobs.source_for(v), short.segments, subs, short.title)
    except ApiError as e:
        short.status, short.error = ShortStatus.FAILED, e.message
        short.save()
        raise
    short.save()
    _apply(short, state)


def refresh(short: Short) -> Short:
    """끝나지 않은 숏폼이면 analyzer 에 상태를 묻고 반영한다. analyzer 에 연결이 안 되면 그대로 둔다."""
    if short.status not in (ShortStatus.QUEUED, ShortStatus.RENDERING):
        return short
    try:
        state = analyzer.get_short(short.key)
    except ApiError as e:
        if e.status == 404:  # analyzer 를 다시 띄워 기록이 없어짐 → 같은 내용으로 다시 맡김
            try:
                _submit(short)
            except ApiError:
                pass
        return short
    _apply(short, state)
    return short


def _apply(short: Short, state: dict) -> None:
    """analyzer 상태를 숏폼에 반영한다. 끝났으면 mp4 를 저장소에 올린다."""
    status = state["status"]
    if status in ("queued", "rendering"):
        if short.status != status:
            short.status = status
            short.save(update_fields=["status"])
        return
    if status == "failed":
        short.status, short.error, short.finished_at = ShortStatus.FAILED, state.get("error") or "렌더 실패", timezone.now()
    else:
        key = f"shorts/{short.key}.mp4"
        try:
            storage.upload_file(OUTPUTS_ROOT / state["output"], key, "video/mp4")
        except Exception as e:  # 저장소 꺼짐, 파일 없음
            short.status, short.error = ShortStatus.FAILED, f"저장소에 올리지 못했습니다: {e}"
        else:
            short.status, short.storage_key, short.error = ShortStatus.DONE, key, ""
            short.render_sec = state.get("render_sec")
        short.finished_at = timezone.now()
    short.save()


def as_json(short: Short) -> dict:
    """17번 응답 형식."""
    return {
        "id": short.id, "game_id": short.video_id, "status": short.status, "event_ids": short.event_ids,
        "segments": short.segments, "subtitles": short.subtitles,
        "duration_sec": round(sum(s["end_sec"] - s["start_sec"] for s in short.segments), 2),
        "video_url": storage.public_url(short.storage_key) if short.status == ShortStatus.DONE else None,
        "render_sec": short.render_sec, "attempts": short.attempts, "error": short.error or None,
        "created_at": short.created_at.isoformat(),
        "finished_at": short.finished_at.isoformat() if short.finished_at else None,
    }
