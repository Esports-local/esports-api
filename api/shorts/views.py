"""경기 이벤트와 숏폼 엔드포인트 (스펙 시트 spec_sheet_lol 14~18번)."""

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


@extend_schema(tags=["shorts"], summary="14. 경기 이벤트 목록 (킬, 타워, 오브젝트) + 숏폼 클립, 추천 장면(scenes)")
@api_view(["GET"])
def game_events(request, pk: int):
    """조건으로 거르지 않고 전부 준다 (거르기는 ui). 요청 글 해석은 18번."""
    v = _video(pk)
    return Response({"events": shorts.events(v), "scenes": shorts.scenes(v)})


@extend_schema(tags=["shorts"], summary="18. 모음 숏폼 요청 글 → 조건 (LLM, 같은 글은 1시간 저장)")
@api_view(["POST"])
def game_shorts_query(request, pk: int):
    v = _video(pk)
    text = request.data.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 200:
        raise ApiError("text 는 1~200자 문자열이어야 합니다")
    return Response(shorts.query(v, text.strip()))


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

