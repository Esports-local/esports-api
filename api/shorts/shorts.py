"""숏폼: 이벤트 → 구간 계산, 같은 요청 판별(key), analyzer 렌더 맡기기·상태 갱신·저장소 업로드.

흐름
1. POST /games/{id}/shorts → 구간·제목으로 key(입력 해시)를 만든다 (자막은 넣지 않는다)
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
from api.games import analyzer, jobs
from config import storage
from matches.models import GameVideo, Player, Short, ShortStatus
from matches.outputs import OUTPUTS_ROOT

PRE_SEC, POST_SEC, MAX_PAD = 6.0, 4.0, 15.0
TYPE_LABEL = {"kill": "킬", "tower": "타워", "objective": "오브젝트"}


def events(v: GameVideo) -> list[dict]:
    """경기 이벤트 + 숏폼 구간(clip). analyzer shorts 단계 결과가 있으면 그 이벤트별 클립(해설 기준 구간,
    선수 이름·챔피언, 뒤따르는 리플레이)을, 없으면 timeline 이벤트 앞 PRE_SEC·뒤 POST_SEC. 둘 다 없으면 404."""
    clips = _result(v, "shorts").get("clips")
    if clips:
        players = _result(v, "context").get("players") or {}
        return [_from_clip(c, players) for c in clips]
    data = v.results.get("timeline")
    if not data:
        raise ApiError("timeline 결과가 없습니다", 404)
    return [{**e, "clip": clip(e, v.duration, PRE_SEC, POST_SEC)} for e in data["result"]["events"]]


def scenes(v: GameVideo) -> list[dict]:
    """추천 장면 후보 (shorts 단계, 대사로 묶은 장면 중 킬·오브젝트가 있는 live 장면). 없으면 빈 목록."""
    res = _result(v, "shorts")
    by_scene: dict[str, list[dict]] = {}
    players = _result(v, "context").get("players") or {}
    for c in res.get("clips") or []:
        if c.get("scene"):
            by_scene.setdefault(c["scene"], []).append(_from_clip(c, players))
    out = []
    for c in res.get("candidates") or []:
        evs = by_scene.get(c["id"], [])
        clip = None
        if c.get("clip_start_sec") is not None and c.get("clip_end_sec") is not None:
            clip = {"start_sec": c["clip_start_sec"], "end_sec": c["clip_end_sec"]}
        out.append({"id": c["id"], "start_sec": c["start_sec"], "end_sec": c["end_sec"],
                    "duration_sec": c["duration_sec"], "cuts": c["cuts"], "events": evs,
                    "rank": c.get("rank"), "title": c.get("title") or auto_title(evs),
                    "titles": c.get("titles") or [], "reason": c.get("reason") or "",
                    "clip": clip, "source": c.get("source"), "warnings": c.get("warnings") or []})
    return sorted(out, key=lambda s: s["rank"] or 999)


def query(v: GameVideo, text: str) -> dict:
    """모음형 요청 글 → 조건 (analyzer LLM). 선수 목록은 context 결과. analyzer 오류는 error 로 돌려준다."""
    players = {slot: f"{p.get('team')} {p.get('name')} ({p.get('champion')})"
               for slot, p in (_result(v, "context").get("players") or {}).items() if p.get("name")}
    from django.core.cache import cache

    ck = "shorts-query:" + hashlib.sha256(json.dumps([v.id, text, players], ensure_ascii=False).encode()).hexdigest()
    if (hit := cache.get(ck)) is not None:  # 같은 요청 글로 다시 열 때(새로고침) LLM 을 다시 부르지 않는다
        return hit
    try:
        res = analyzer.parse_query(text, players)
    except ApiError as e:
        return {"text": text, "filter": {}, "title": None, "note": None, "error": e.message}  # 실패는 저장 안 함
    out = {"text": text, **res}
    if not res.get("error"):
        cache.set(ck, out, 60 * 60)
    return out


def _result(v: GameVideo, stage: str) -> dict:
    return ((v.results or {}).get(stage) or {}).get("result") or {}


def _who(players: dict, slot: str | None) -> dict | None:
    if not slot:
        return None
    p = players.get(slot) or {}
    return {"slot": slot, "name": p.get("name"), "champion": p.get("champion"), "team": p.get("team")}


def _from_clip(c: dict, players: dict) -> dict:
    """shorts 단계 이벤트 클립 → 14번 이벤트 모양 (players 는 예전 모양과 같게 이름 목록도 둔다)."""
    killer = _who(players, c.get("killer"))
    victims = [_who(players, s) for s in c.get("victims") or []]
    assists = [_who(players, s) for s in c.get("assists") or []]
    names = lambda ws: [w["name"] or w["slot"] for w in ws if w]
    return {"id": c["event_id"], "type": c["type"], "subtype": c.get("subtype"), "team": c.get("team"),
            "team_name": (killer or {}).get("team"), "t": c["t"], "start_sec": c["t"], "end_sec": c["t"],
            "game_time": c.get("game_time"), "killer": killer, "victims": victims, "assists": assists,
            "players": {k: v for k, v in (("killer", names([killer])), ("victims", names(victims)),
                                          ("assists", names(assists))) if v},
            "tags": c.get("tags") or [], "area": c.get("area"), "on_screen": c.get("on_screen"),
            "scene": c.get("scene"), "clip": {"start_sec": c["start_sec"], "end_sec": c["end_sec"]},
            "replay": c.get("replay"), "score": c.get("score")}


OBJECT_LABEL = {"dragon": "용", "elder": "장로", "baron": "바론", "herald": "전령", "grubs": "유충", "atakhan": "아타칸"}
DRAKE_LABEL = {"water": "바다", "fire": "화염", "earth": "대지", "air": "바람", "hextech": "마법공학", "chemtech": "화학공학"}


def auto_title(evs: list[dict]) -> str:
    """자동 제목 (10자 안쪽): "Ruler 킬" / "킬 2 · 용" """
    kills = [e for e in evs if e["type"] == "kill"]
    objs = [OBJECT_LABEL.get((e.get("subtype") or "").split(":")[0], "오브젝트") for e in evs if e["type"] == "objective"]
    if len(kills) == 1 and not objs and kills[0].get("killer"):
        return f"{kills[0]['killer']['name'] or kills[0]['killer']['slot']} 킬"
    parts = ([f"킬 {len(kills)}"] if kills else []) + sorted(set(objs))
    return " · ".join(parts) or "장면"


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
    """숏폼 이름 (영상에는 그리지 않음): "T1 vs BLG · Doran 킬" / 여러 개면 "T1 vs BLG · 킬 2, 타워 1"."""
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


LAYOUT_VERSION = "v3"  # 렌더 화면 구성 (v2: 11-23 위 제목 + 가운데 1180x1080 + 설명 자막, v3: 자막을 킬 시각부터). 바꾸면 다시 렌더


def make_key(v: GameVideo, segments: list[dict], title: str, event_ids: list | None = None,
             ov: dict | None = None) -> str:
    """같은 입력이면 같은 key. timeline 을 다시 돌리거나(created_at 이 바뀜) 화면 구성·영상 위 글자(선수 이름 사전을
    고친 경우 포함)가 바뀌면 다른 key."""
    version = (v.results.get("timeline") or {}).get("created_at", "")
    raw = json.dumps({"work": v.work_name, "version": version, "segments": segments, "title": title,
                      "events": sorted(event_ids or []), "layout": LAYOUT_VERSION, "overlay": ov or {}},
                     ensure_ascii=False, sort_keys=True)
    return "s" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def match_line(v: GameVideo) -> str:
    """영상 위 제목 첫 줄: "2026 LCK 결승 1세트" (경기 정보가 없으면 영상 이름)."""
    m = (v.header or {}).get("match") or {}
    if not m:
        return v.title
    stage = "결승" if "final" in (m.get("name") or "").lower() else ""
    return " ".join(str(x) for x in (m.get("year"), m.get("league"), stage, f"{m['set']}세트" if m.get("set") else "") if x)


def overlay(v: GameVideo, event_ids: list, segments: list[dict], title: str) -> dict:
    """렌더에 넘길 위 제목 줄과 설명 자막 (이벤트 데이터로 틀을 채움, LLM 없음).

    킬: "{킬한 선수}, {당한 선수} 잡고" / "킬 {블루 팀} {점수} : {점수} {레드 팀}" (당한 선수를 모르면 "{킬한 선수} 킬").
    선수 이름은 Player 사전으로 한국어로 바꾼다 (없으면 영어 그대로).
    오브젝트: "{팀} {용 종류·바론…}". 타워는 넣지 않는다. 이벤트 시각(op.gg)부터 다음 자막 전까지(길어도 6초).
    """
    try:
        evs = {e["id"]: e for e in events(v)}
    except ApiError:
        evs = {}
    teams = {s: ((v.header or {}).get("teams") or {}).get(s, {}).get("name") or s.upper() for s in ("blue", "red")}
    t_of = lambda e: e.get("t", e.get("end_sec", 0.0))  # 예전 timeline 이벤트는 t 가 없다
    inside = lambda t: any(s["start_sec"] <= t <= s["end_sec"] for s in segments)
    picked = sorted((evs[i] for i in event_ids if i in evs and inside(t_of(evs[i]))), key=t_of)
    ko = Player.ko_map()
    nm = lambda n: ko.get((n or "").lower(), n)
    caps = []
    for e in picked:
        killer = nm((e.get("killer") or {}).get("name")) if isinstance(e.get("killer"), dict) else None
        if e["type"] == "kill" and killer:
            victims = [nm(w["name"]) for w in e.get("victims") or [] if isinstance(w, dict) and w.get("name")]
            lines = [f"{killer}, {', '.join(victims)} 잡고" if victims else f"{killer} 킬"]
            if e.get("score"):
                lines.append(f"킬 {teams['blue']} {e['score']['blue']} : {e['score']['red']} {teams['red']}")
        elif e["type"] == "objective":
            kind, _, drake = (e.get("subtype") or "").partition(":")
            label = f"{DRAKE_LABEL.get(drake, '')} 용".strip() if kind == "dragon" else OBJECT_LABEL.get(kind, "오브젝트")
            lines = [f"{teams.get(e.get('team'), '')} {label}".strip()]
        else:
            continue
        caps.append({"start_sec": round(t_of(e), 2), "end_sec": round(t_of(e) + 6.0, 2), "lines": lines})
    for a, b in zip(caps, caps[1:]):  # 다음 자막이 나오면 앞 자막은 끝
        a["end_sec"] = min(a["end_sec"], b["start_sec"])
    return {"title_lines": [x for x in (match_line(v), title) if x], "captions": caps}


def request(v: GameVideo, event_ids: list[int], pre: float, post: float) -> tuple[Short, bool]:
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
    title = title_for(v, picked)
    key = make_key(v, segments, title, event_ids, overlay(v, sorted(event_ids), segments, title))

    return _get_or_submit(v, key, sorted(event_ids), segments, title)


def request_segments(v: GameVideo, segments: list[dict], title: str, event_ids: list | None = None) -> tuple[Short, bool]:
    """구간 목록으로 숏폼을 요청한다 (추천 장면·모음). 겹치는 구간은 합친다.

    Raises:
        ApiError: 잘못된 구간(400), analyzer 연결 실패(502).
    """
    spans = []
    for s in segments:
        a, b = (s.get("start_sec"), s.get("end_sec")) if isinstance(s, dict) else (None, None)
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (a, b)) or not 0 <= a < b:
            raise ApiError("segments 는 [{start_sec, end_sec}] 이고 0 <= start_sec < end_sec 여야 합니다")
        if v.duration and b > v.duration + 1:
            raise ApiError(f"구간이 영상 길이({v.duration:.0f}초)를 넘습니다")
        spans.append({"start_sec": round(float(a), 2), "end_sec": round(float(b), 2)})
    segs = merge(spans)
    key = make_key(v, segs, title, event_ids, overlay(v, sorted(event_ids or []), segs, title))
    return _get_or_submit(v, key, sorted(event_ids or []), segs, title)


def _get_or_submit(v: GameVideo, key: str, event_ids: list, segments: list[dict], title: str) -> tuple[Short, bool]:
    """같은 key 숏폼이 있으면 그것 (실패한 것이면 다시 맡김), 없으면 만들고 analyzer 에 맡긴다."""
    short = Short.objects.filter(key=key).first()
    created = short is None
    if created:
        try:
            with transaction.atomic():
                short = Short.objects.create(video=v, key=key, event_ids=event_ids, segments=segments, title=title)
        except IntegrityError:  # 같은 요청이 동시에 들어옴
            short, created = Short.objects.get(key=key), False
    if created or short.status == ShortStatus.FAILED:
        _submit(short)
    return short, created


def _submit(short: Short) -> None:
    """analyzer 에 렌더를 맡긴다 (시도 횟수 +1). analyzer 오류는 failed 로 남기고 다시 던진다."""
    v = short.video
    short.attempts += 1
    short.status, short.error, short.finished_at = ShortStatus.QUEUED, "", None
    try:
        # 구간 분석 영상(playback_name)도 원본 기준 시각이라 원본 파일을 그대로 자른다
        ov = overlay(v, short.event_ids, short.segments, short.title)
        state = analyzer.create_short(short.key, v.playback_name or jobs.source_for(v), short.segments, short.title,
                                      ov["title_lines"], ov["captions"])
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
            short.bgm = state.get("bgm") or {}
        short.finished_at = timezone.now()
    short.save()


def as_json(short: Short) -> dict:
    """17번 응답 형식."""
    return {
        "id": short.id, "game_id": short.video_id, "status": short.status, "event_ids": short.event_ids,
        "segments": short.segments, "title": short.title, "bgm": short.bgm or None,
        "duration_sec": round(sum(s["end_sec"] - s["start_sec"] for s in short.segments), 2),
        "video_url": storage.public_url(short.storage_key) if short.status == ShortStatus.DONE else None,
        "render_sec": short.render_sec, "attempts": short.attempts, "error": short.error or None,
        "created_at": short.created_at.isoformat(),
        "finished_at": short.finished_at.isoformat() if short.finished_at else None,
    }
