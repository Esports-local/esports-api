"""/games·/sources 엔드포인트 (스펙 시트 spec_sheet_lol 1~5번, 8~13번)."""

from django.db import transaction
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.exceptions import ApiError, get_or_404
from api.games import analyzer, jobs, reviews
from matches import opgg
from matches.management.commands.import_match import save_match
from matches.models import GameVideo, LineReview, Match, MatchGame, Role
from matches.screen import filter_runs, snapshot, static_values

GAME_NOT_FOUND = "영상을 찾을 수 없습니다"
STAGES = ["preprocess", "segments", "hls", "roi_ocr", "asr", "translate", "evaluate"]
RUNNABLE = ["preprocess", "roi_ocr", "asr", "translate"]  # ui 에서 고를 수 있는 단계
ROLE_ORDER = [r.value for r in Role]


def _video(pk: int) -> GameVideo:
    return get_or_404(GameVideo.objects.select_related("game__match", "game__blue_team", "game__red_team"),
                      pk, GAME_NOT_FOUND)


def _stage(v: GameVideo, stage: str, message: str) -> dict:
    data = v.results.get(stage)
    if not data:
        raise Http404(message)
    return data["result"]


def _teams(v: GameVideo):
    g = v.game
    if not g or not (g.blue_team and g.red_team):
        return None
    return {"blue": g.blue_team.acronym, "red": g.red_team.acronym}


def _match(v: GameVideo):
    g = v.game
    if not g:
        return None
    m = g.match
    winner = None
    if g.winner_id:
        winner = "blue" if g.winner_id == g.blue_team_id else "red"
    sides = {}
    for side, team in (("blue", g.blue_team), ("red", g.red_team)):
        players = {p.role: {"name": p.name, "champion": p.champion or None, "champion_ko": p.champion_ko or None}
                   for p in g.players.all() if p.side == side}
        sides[side] = {"team": team.acronym if team else None,
                       "players": {r: players[r] for r in ROLE_ORDER if r in players}}
    return {"opgg_id": m.opgg_id, "name": m.name, "tournament": f"{m.league} {m.year or ''}".strip(),
            "stage": m.stage, "date": m.begin_at.isoformat() if m.begin_at else None, "game": g.number,
            "score": {m.home_team.acronym: m.home_score, m.away_team.acronym: m.away_score},
            "winner": winner, "video_url": g.full_video_url or None, "source_url": m.source_url, **sides}


def _stages(v: GameVideo):
    logged = {x["stage"]: x for x in v.run_log}
    out = []
    for s in STAGES:
        if s in logged:
            out.append({"stage": s, "status": "done", "elapsed_sec": logged[s].get("elapsed_sec")})
        elif s in v.results:
            out.append({"stage": s, "status": "done", "elapsed_sec": None})
        else:
            out.append({"stage": s, "status": "pending", "elapsed_sec": None})
    return out


def _summary(v: GameVideo) -> dict:
    return {"id": v.id, "title": v.title, "language": v.language, "duration_sec": v.duration,
            "teams": _teams(v), "analyze_status": v.analyze_status}


def _detail(v: GameVideo, job: dict | None) -> dict:
    progress = None
    if job:
        progress = {"current_stage": job.get("current_stage"), "stages": job.get("stages"),
                    "elapsed_sec": job.get("elapsed_sec")}
    return {**_summary(v), "video": v.video_name or None, "video_url": None, "stages": _stages(v),
            "progress": progress, "error": v.error or None, "match": _match(v)}


def _stage_list(raw) -> list[str]:
    stages = raw if isinstance(raw, list) else jobs.DEFAULT_STAGES
    bad = [s for s in stages if s not in RUNNABLE]
    if not stages or bad:
        raise ApiError(f"stages 는 {RUNNABLE} 중에서 고릅니다: {bad or '없음'}")
    return [s for s in RUNNABLE if s in stages]


def _translate_params(data) -> dict:
    conds = data.get("conditions")
    if conds is None:
        return {}
    if not isinstance(conds, list) or not conds or set(conds) - {"A", "B", "C"}:
        raise ApiError("conditions 는 A, B, C 중에서 고릅니다")
    return {"translate": {"conditions": conds}}


def _match_game(data) -> MatchGame | None:
    """요청의 match(op.gg 번호)·set 으로 세트를 찾는다. 경기가 없으면 op.gg 에서 가져온다."""
    match_no, set_no = data.get("match"), data.get("set")
    if match_no in (None, "") and set_no in (None, ""):
        return None
    try:
        match_no, set_no = int(match_no), int(set_no)
    except (TypeError, ValueError) as e:
        raise ApiError("match 와 set 은 숫자여야 합니다") from e
    if not Match.objects.filter(opgg_id=match_no).exists():
        try:
            url, d = opgg.fetch_match(str(match_no))
        except (ValueError, OSError) as e:
            raise ApiError(f"op.gg 경기 {match_no} 를 가져오지 못했습니다: {e}", 502) from e
        save_match(url, d)
    game = MatchGame.objects.filter(match__opgg_id=match_no, number=set_no).first()
    if game is None:
        raise ApiError(f"경기 {match_no} 에 {set_no}세트가 없습니다", 404)
    return game


@extend_schema(methods=["GET"], tags=["games"], summary="1. 세트 영상 목록")
@extend_schema(methods=["POST"], tags=["games"], summary="8. 세트 영상 등록 + 분석 시작")
@api_view(["GET", "POST"])
def game_list(request):
    if request.method == "GET":
        qs = GameVideo.objects.select_related("game__blue_team", "game__red_team")
        for v in qs:
            jobs.refresh(v)
        return Response([_summary(v) for v in qs])

    data = request.data
    name = data.get("video") or ""
    source = next((s for s in analyzer.list_videos() if s["name"] == name), None)
    if source is None:
        raise ApiError(f"영상이 없습니다: {name}", 404)
    if not source["selectable"]:
        raise ApiError(f"고를 수 없는 영상입니다: {source.get('reason')}")
    language = data.get("language") or "ko"
    if language not in ("ko", "en"):
        raise ApiError("language 는 ko 또는 en 입니다")
    stages = _stage_list(data.get("stages"))
    params = _translate_params(data)
    game = _match_game(data)
    work_name = name.rsplit(".", 1)[0]
    with transaction.atomic():
        v, _ = GameVideo.objects.get_or_create(work_name=work_name, defaults={"title": work_name})
        if v.analyze_status == "running":
            raise ApiError("이미 분석 중입니다", 409)
        v.title = (data.get("title") or "").strip() or v.title
        v.language, v.video_name, v.game = language, name, game or v.game
        v.save()
    jobs.start(v, stages, params)
    return Response(_detail(v, None), status=201)


@extend_schema(tags=["games"], summary="2. 세트 상세 + 단계 상태 + 경기 정보 (분석 중이면 진행 상태)")
@api_view(["GET"])
def game_detail(request, pk: int):
    v = _video(pk)
    job = jobs.refresh(v)
    return Response(_detail(v, job))


@extend_schema(tags=["games"], summary="9. 단계 추가 실행 (예: 번역)")
@api_view(["POST"])
def game_analyze(request, pk: int):
    v = _video(pk)
    jobs.refresh(v)
    jobs.start(v, _stage_list(request.data.get("stages")), _translate_params(request.data))
    return Response(_detail(v, None), status=202)


@extend_schema(tags=["games"], summary="10. 분석 중지")
@api_view(["POST"])
def game_cancel(request, pk: int):
    v = _video(pk)
    if v.analyze_status == "running" and v.job_id:
        analyzer.cancel_job(v.job_id)
    return Response(_detail(v, jobs.refresh(v)))


@extend_schema(tags=["games"], summary="11. 번역 예상 입력 토큰")
@api_view(["GET"])
def game_estimate(request, pk: int):
    v = _video(pk)
    conds = [c for c in request.query_params.get("conditions", "A,B").split(",") if c]
    if not conds or set(conds) - {"A", "B", "C"}:
        raise ApiError("conditions 는 A, B, C 중에서 고릅니다")
    return Response(analyzer.estimate(jobs.source_for(v), conds, reviews.text_overrides(v)))


@extend_schema(tags=["games"], summary="12. 고를 수 있는 원본 영상 목록")
@api_view(["GET"])
def source_list(request):
    registered = {v.video_name: v.id for v in GameVideo.objects.exclude(video_name="")}
    by_work = {v.work_name: v.id for v in GameVideo.objects.all()}
    out = []
    for s in analyzer.list_videos():
        game_id = registered.get(s["name"]) or by_work.get(s["name"].rsplit(".", 1)[0])
        out.append({**s, "game_id": game_id})
    return Response(out)


@extend_schema(tags=["games"], summary="3. 화면 OCR 구간")
@api_view(["GET"])
def game_screen(request, pk: int):
    r = _stage(_video(pk), "roi_ocr", "화면 분석 결과가 없습니다")
    tags = {t for t in request.query_params.get("tag", "").split(",") if t.strip()} or None
    try:
        min_samples = int(request.query_params.get("min_samples", 2))
    except ValueError as e:
        raise ApiError("min_samples 는 정수여야 합니다") from e
    runs = filter_runs(r["runs"], tags, min_samples)
    return Response({"layout": r["layout"], "sample_fps": r["sample_fps"], "runs": runs})


def _float_param(request, name):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError as e:
        raise ApiError(f"{name} 는 숫자여야 합니다") from e


@extend_schema(tags=["games"], summary="4. 해설 대사 + 화면 정보 + 조건별 번역")
@api_view(["GET"])
def game_lines(request, pk: int):
    v = _video(pk)
    lines = _stage(v, "asr", "대사 분석 결과가 없습니다")["lines"]
    runs = (v.results.get("roi_ocr") or {}).get("result", {}).get("runs", [])
    statics = static_values(runs)
    translations = ((v.results.get("translate") or {}).get("result") or {}).get("lines", {})
    lo, hi = _float_param(request, "from_sec"), _float_param(request, "to_sec")
    checked = reviews.current(v, lines)
    out = []
    for line in lines:
        if (lo is not None and line["start_sec"] < lo) or (hi is not None and line["start_sec"] > hi):
            continue
        mid = (line["start_sec"] + line["end_sec"]) / 2
        out.append({"id": line["id"], "start_sec": line["start_sec"], "end_sec": line["end_sec"],
                    "language": line.get("language"), "text": line["text"],
                    "screen": snapshot(runs, mid, statics) if runs else {},
                    "translations": translations.get(str(line["id"])),
                    "review": reviews.as_json(checked.get(line["id"]))})
    return Response(out)


@extend_schema(tags=["games"], summary="13. 대사 검수 저장 (고친 문장, 검수 O/X)")
@api_view(["POST"])
def game_line_review(request, pk: int, line_id: int):
    v = _video(pk)
    line = next((x for x in _stage(v, "asr", "대사 분석 결과가 없습니다")["lines"] if x["id"] == line_id), None)
    if line is None:
        raise Http404("대사를 찾을 수 없습니다")
    text, reviewed = request.data.get("text"), request.data.get("reviewed")
    if text is None and reviewed is None:
        raise ApiError("text 나 reviewed 중 하나는 보내야 합니다")
    if text is not None and (not isinstance(text, str) or not text.strip()):
        raise ApiError("text 는 비어 있지 않은 문자열이어야 합니다")
    if reviewed is not None and not isinstance(reviewed, bool):
        raise ApiError("reviewed 는 true 또는 false 입니다")
    r = reviews.current(v, [line]).get(line_id)
    if r is None:  # 처음 검수하거나 asr 를 다시 돌려 원문이 바뀜 → 새로 시작
        r = LineReview.objects.filter(video=v, line_id=line_id).first() or LineReview(video=v, line_id=line_id)
        r.asr_text, r.text, r.reviewed = line["text"], "", False
    if text is not None:
        text = text.strip()
        r.text = "" if text == line["text"] else text  # 원문과 같으면 안 고친 것
    if reviewed is not None:
        r.reviewed = reviewed
    r.save()
    return Response({"id": line_id, "text": line["text"], "review": reviews.as_json(r)})


@extend_schema(tags=["games"], summary="5. 단계 결과 원본")
@api_view(["GET"])
def game_analysis(request, pk: int):
    stage = request.query_params.get("stage", "")
    if stage not in STAGES:
        raise ApiError(f"알 수 없는 단계입니다: {stage}")
    v = _video(pk)
    data = v.results.get(stage)
    if not data:
        raise Http404(f"{stage} 결과가 없습니다")
    return Response(data)
