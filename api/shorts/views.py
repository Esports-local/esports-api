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


@extend_schema(tags=["shorts"], summary="14. 경기 이벤트 목록 (킬, 타워, 오브젝트) + 숏폼 기본 구간")
@api_view(["GET"])
def game_events(request, pk: int):
    v = _video(pk)
    etype = request.query_params.get("type")
    if etype and etype not in shorts.EVENT_TYPES:
        raise ApiError(f"알 수 없는 이벤트 종류입니다: {etype}")
    player = (request.query_params.get("player") or "").strip().lower()
    out = []
    for e in shorts.events(v):
        if etype and e["type"] != etype:
            continue
        if player and not any(player == p.lower() for names in e.get("players", {}).values() for p in names):
            continue
        out.append(e)
    return Response({"events": out})


@extend_schema(methods=["GET"], tags=["shorts"], summary="16. 세트의 숏폼 목록 (최근순)")
@extend_schema(methods=["POST"], tags=["shorts"], summary="15. 숏폼 만들기 (같은 요청은 기존 숏폼)")
@api_view(["GET", "POST"])
def game_shorts(request, pk: int):
    v = _video(pk)
    if request.method == "GET":
        return Response({"shorts": [shorts.as_json(s) for s in v.shorts.all()]})
    data = request.data
    ids = data.get("event_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ApiError("event_ids 는 이벤트 번호 목록이어야 합니다")
    if len(set(ids)) > shorts.MAX_EVENTS:
        raise ApiError(f"이벤트는 {shorts.MAX_EVENTS}개까지 고를 수 있습니다")
    short, created = shorts.request(v, sorted(set(ids)), _pad(data, "pre_sec", shorts.PRE_SEC),
                                    _pad(data, "post_sec", shorts.POST_SEC))
    return Response(shorts.as_json(short), status=201 if created else 200)


@extend_schema(tags=["shorts"], summary="17. 숏폼 상태와 결과 (끝나지 않았으면 analyzer 상태로 갱신)")
@api_view(["GET"])
def short_detail(request, pk: int):
    short = get_or_404(Short.objects.select_related("video"), pk, "숏폼을 찾을 수 없습니다")
    return Response(shorts.as_json(shorts.refresh(short)))

