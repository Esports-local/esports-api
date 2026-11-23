"""경기 이벤트와 숏폼 엔드포인트 (스펙 시트 spec_sheet_lol 14~17번)."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.exceptions import ApiError, get_or_404
from api.games.views import _video
from api.shorts import shorts
from matches.models import Short


def _pad(data, name: str, default: float) -> float:
    value = data.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= shorts.MAX_PAD:
        raise ApiError(f"{name} 는 0~{shorts.MAX_PAD:.0f} 사이 숫자여야 합니다")
    return float(value)


@extend_schema(tags=["shorts"], summary="14. 경기 이벤트 목록 (킬, 타워, 오브젝트) + 숏폼 구간, 추천 장면(scenes), q 로 요청 글 해석")
@api_view(["GET"])
def game_events(request, pk: int):
    v = _video(pk)
    etype = request.query_params.get("type")
    if etype and etype not in shorts.EVENT_TYPES:
        raise ApiError(f"알 수 없는 이벤트 종류입니다: {etype}")
    player = (request.query_params.get("player") or "").strip().lower()  # 선수 이름 또는 슬롯 (킬·데스·도움 어디든)
    killer = (request.query_params.get("killer") or "").strip().lower()  # 킬한 선수 이름 또는 슬롯
    team = (request.query_params.get("team") or "").strip().lower()      # blue · red 또는 팀 이름
    tag = (request.query_params.get("tag") or "").strip()
    q = (request.query_params.get("q") or "").strip()[:200]
    parsed = None
    if q:  # 요청 글 → 조건 (LLM). 직접 준 조건이 먼저
        parsed = shorts.query(v, q)
        f = parsed.get("filter") or {}
        etype = etype or f.get("type")
        killer = killer or (f.get("killer") or "").lower()
        team = team or f.get("team") or ""
        tag = tag or f.get("tag") or ""
    out = []
    for e in shorts.events(v):
        if etype and e["type"] != etype:
            continue
        if player and not any(player == p.lower() for names in e.get("players", {}).values() for p in names) \
                and player not in _slots(e):
            continue
        if killer and killer not in {((e.get("killer") or {}).get("name") or "").lower(),
                                     ((e.get("killer") or {}).get("slot") or "").lower()} \
                and killer not in [p.lower() for p in e.get("players", {}).get("killer", [])]:
            continue
        if team and team not in {(e.get("team") or "").lower(), (e.get("team_name") or "").lower()}:
            continue
        if tag and tag not in e.get("tags", []):
            continue
        out.append(e)
    body = {"events": out, "scenes": shorts.scenes(v)}
    if parsed is not None:
        body["query"] = parsed
    return Response(body)


def _slots(e: dict) -> set[str]:
    return {w["slot"] for k in ("killer", "victims", "assists")
            for w in ([e.get(k)] if isinstance(e.get(k), dict) else e.get(k) or []) if isinstance(w, dict)}


@extend_schema(methods=["GET"], tags=["shorts"], summary="16. 세트의 숏폼 목록 (최근순)")
@extend_schema(methods=["POST"], tags=["shorts"], summary="15. 숏폼 만들기 (같은 요청은 기존 숏폼)")
@api_view(["GET", "POST"])
def game_shorts(request, pk: int):
    v = _video(pk)
    if request.method == "GET":
        return Response({"shorts": [shorts.as_json(s) for s in v.shorts.all()]})
    data = request.data
    if "segments" in data:  # 추천 장면·모음: 구간 목록 + 제목
        segs, title = data.get("segments"), data.get("title", "")
        if not isinstance(segs, list) or not segs:
            raise ApiError("segments 는 구간 목록이어야 합니다")
        if not isinstance(title, str) or len(title) > 200:
            raise ApiError("title 은 200자 이하 문자열이어야 합니다")
        ids = data.get("event_ids") or []
        if not isinstance(ids, list):
            raise ApiError("event_ids 는 목록이어야 합니다")
        short, created = shorts.request_segments(v, segs, title.strip(), ids)
        return Response(shorts.as_json(short), status=201 if created else 200)
    ids = data.get("event_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ApiError("event_ids 는 이벤트 번호 목록이어야 합니다")
    short, created = shorts.request(v, sorted(set(ids)), _pad(data, "pre_sec", shorts.PRE_SEC),
                                    _pad(data, "post_sec", shorts.POST_SEC))
    return Response(shorts.as_json(short), status=201 if created else 200)


@extend_schema(tags=["shorts"], summary="17. 숏폼 상태와 결과 (끝나지 않았으면 analyzer 상태로 갱신)")
@api_view(["GET"])
def short_detail(request, pk: int):
    short = get_or_404(Short.objects.select_related("video"), pk, "숏폼을 찾을 수 없습니다")
    return Response(shorts.as_json(shorts.refresh(short)))

