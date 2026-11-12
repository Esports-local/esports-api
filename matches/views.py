"""세트 영상 엔드포인트 (스펙 시트 spec_sheet_lol 1~5번)."""

from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from matches.models import GameVideo, Role
from matches.screen import filter_runs, snapshot, static_values
from vod.exceptions import ApiError

GAME_NOT_FOUND = "영상을 찾을 수 없습니다"
STAGES = ["preprocess", "segments", "hls", "roi_ocr", "asr", "translate", "evaluate"]
ROLE_ORDER = [r.value for r in Role]


def _video(pk: int) -> GameVideo:
    v = GameVideo.objects.select_related("game__match", "game__blue_team", "game__red_team").filter(pk=pk).first()
    if v is None:
        raise Http404(GAME_NOT_FOUND)
    return v


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


@extend_schema(tags=["games"], summary="1. 세트 영상 목록")
@api_view(["GET"])
def game_list(request):
    qs = GameVideo.objects.select_related("game__blue_team", "game__red_team")
    return Response([_summary(v) for v in qs])


@extend_schema(tags=["games"], summary="2. 세트 상세 + 단계 상태 + 경기 정보")
@api_view(["GET"])
def game_detail(request, pk: int):
    v = _video(pk)
    return Response({**_summary(v), "video_url": None, "stages": _stages(v), "match": _match(v)})


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
    out = []
    for line in lines:
        if (lo is not None and line["start_sec"] < lo) or (hi is not None and line["start_sec"] > hi):
            continue
        mid = (line["start_sec"] + line["end_sec"]) / 2
        out.append({"id": line["id"], "start_sec": line["start_sec"], "end_sec": line["end_sec"],
                    "language": line.get("language"), "text": line["text"],
                    "screen": snapshot(runs, mid, statics) if runs else {},
                    "translations": translations.get(str(line["id"]))})
    return Response(out)


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
