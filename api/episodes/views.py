"""/episodes 엔드포인트 (드라마 스펙 5~8번)."""

from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.episodes.serializers import (
    EpisodeDetailSerializer,
    LineReviewListSerializer,
    LineReviewRequestSerializer,
    LineReviewSavedSerializer,
    LineReviewSerializer,
)
from api.exceptions import ApiError, get_or_404
from api.serializers import ErrorSerializer
from vod.models import Episode, JobStatus, LineReview, Verdict

EPISODE_NOT_FOUND = "회차를 찾을 수 없습니다"
ANALYSIS_NOT_FOUND = "분석 결과가 없습니다"
LINE_NOT_FOUND = "대사를 찾을 수 없습니다"


@extend_schema(tags=["episodes"], summary="5. 회차 상세 + 재생 주소",
               responses={200: EpisodeDetailSerializer, 404: ErrorSerializer})
@api_view(["GET"])
def episode_detail(request, pk: int):
    ep = get_or_404(Episode.objects, pk, EPISODE_NOT_FOUND)
    return Response(EpisodeDetailSerializer(ep).data)


def _analyzed_episode(pk: int) -> Episode:
    """분석 결과가 있는 회차. 회차가 없거나 분석 결과가 없으면 404."""
    ep = get_or_404(Episode.objects, pk, EPISODE_NOT_FOUND)
    if ep.analyze_status != JobStatus.DONE or not ep.analysis:
        raise Http404(ANALYSIS_NOT_FOUND)
    return ep


@extend_schema(tags=["episodes"], summary="6. 회차 분석 결과 원본 (main episode.json, start_sec/end_sec)",
               responses={200: OpenApiTypes.OBJECT, 404: ErrorSerializer})
@api_view(["GET"])
def episode_analysis(request, pk: int):
    return Response(_analyzed_episode(pk).analysis)


@extend_schema(methods=["GET"], tags=["episodes"], summary="7. 대사 검수 목록",
               responses={200: LineReviewListSerializer, 404: ErrorSerializer})
@extend_schema(methods=["POST"], tags=["episodes"], summary="8. 대사 판정 저장 (clear 면 지움)",
               request=LineReviewRequestSerializer,
               responses={200: LineReviewSavedSerializer, 400: ErrorSerializer, 404: ErrorSerializer})
@api_view(["GET", "POST"])
def episode_reviews(request, pk: int):
    ep = _analyzed_episode(pk)
    if request.method == "GET":
        items = LineReviewSerializer(ep.line_reviews.all(), many=True).data
        return Response({"episode_id": ep.id, "items": items})

    req = LineReviewRequestSerializer(data=request.data)
    req.is_valid(raise_exception=True)
    scene_id, index, verdict = (req.validated_data[k] for k in ("scene_id", "index", "verdict"))
    text = (req.validated_data.get("text") or "").strip()

    scene = next((sc for sc in ep.analysis.get("scenes", []) if sc.get("id") == scene_id), None)
    lines = scene.get("lines", []) if scene else []
    if index >= len(lines):
        raise Http404(LINE_NOT_FOUND)

    if verdict == "clear":
        ep.line_reviews.filter(scene_id=scene_id, index=index).delete()
        return Response({"review": None})
    if verdict == Verdict.FIXED and (not text or text == lines[index].get("text", "").strip()):
        raise ApiError("고친 대사를 입력해 주세요")
    review, _ = LineReview.objects.update_or_create(
        episode=ep, scene_id=scene_id, index=index,
        defaults={"verdict": verdict, "text": text if verdict == Verdict.FIXED else ""},
    )
    return Response({"review": LineReviewSerializer(review).data})
