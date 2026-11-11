"""ui → api 엔드포인트. 스펙은 스펙 시트(spec_seat 탭 + 엔드포인트별 탭) 기준."""

from django.conf import settings
from django.db import connection
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as s
from rest_framework.decorators import api_view
from rest_framework.response import Response

from vod import predict, storage
from vod.exceptions import ApiError
from vod.models import Episode, JobStatus, LineReview, Prediction, Series, Verdict
from vod.serializers import (
    EpisodeDetailSerializer,
    ErrorSerializer,
    LineReviewListSerializer,
    LineReviewRequestSerializer,
    LineReviewSavedSerializer,
    LineReviewSerializer,
    PredictAcceptedSerializer,
    PredictionSerializer,
    PredictRequestSerializer,
    SeriesDetailSerializer,
    SeriesListSerializer,
)


SERIES_NOT_FOUND = "작품을 찾을 수 없습니다"
EPISODE_NOT_FOUND = "회차를 찾을 수 없습니다"
ANALYSIS_NOT_FOUND = "분석 결과가 없습니다"
LINE_NOT_FOUND = "대사를 찾을 수 없습니다"


def _get_or_404(queryset, pk: int, message: str):
    """pk 로 하나를 찾고, 없으면 {"error": message} 404."""
    obj = queryset.filter(pk=pk).first()
    if obj is None:
        raise Http404(message)
    return obj


# ---------------------------------------------------------------- 상태

@extend_schema(tags=["health"], summary="서비스 상태 (db·storage)", responses={200: inline_serializer("Health", {
    "status": s.CharField(), "db": s.CharField(), "storage": s.CharField()})})
@api_view(["GET"])
def health(request):
    """서비스 상태. db·storage 중 하나라도 실패하면 503."""
    checks = {}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:  # noqa: BLE001 — 상태 보고용
        checks["db"] = f"error: {e}"
    try:
        storage.client().head_bucket(Bucket=settings.S3_BUCKET)
        checks["storage"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["storage"] = f"error: {e}"
    ok = all(v == "ok" for v in checks.values())
    return Response({"status": "ok" if ok else "error", **checks}, status=200 if ok else 503)


# ---------------------------------------------------------------- series

@extend_schema(tags=["series"], summary="1. 작품 목록", responses=SeriesListSerializer(many=True))
@api_view(["GET"])
def series_list(request):
    return Response(SeriesListSerializer(Series.objects.all(), many=True).data)


@extend_schema(tags=["series"], summary="2. 작품 상세 + 회차 목록 + 등장인물",
               responses={200: SeriesDetailSerializer, 404: ErrorSerializer})
@api_view(["GET"])
def series_detail(request, pk: int):
    series = _get_or_404(Series.objects.prefetch_related("episodes", "characters"), pk, SERIES_NOT_FOUND)
    return Response(SeriesDetailSerializer(series).data)


@extend_schema(methods=["POST"], tags=["series"], summary="3. target 회차 예측 시작",
               request=PredictRequestSerializer,
               responses={202: PredictAcceptedSerializer, 400: ErrorSerializer, 404: ErrorSerializer})
@extend_schema(methods=["GET"], tags=["series"], summary="4. 예측 상태 + 결과",
               parameters=[OpenApiParameter("target", int, required=True, description="예측한 회차 번호 (2 이상)")],
               responses={200: PredictionSerializer, 400: ErrorSerializer, 404: ErrorSerializer})
@api_view(["GET", "POST"])
def series_predict(request, pk: int):
    series = _get_or_404(Series.objects, pk, SERIES_NOT_FOUND)
    if request.method == "POST":
        return _start_predict(series, request.data)

    query = PredictRequestSerializer(data=request.query_params)  # POST 와 같은 검증
    query.is_valid(raise_exception=True)
    target = query.validated_data["target"]
    p = Prediction.objects.filter(series=series, target=target).first()
    if p is None:
        return Response({"series_id": series.id, "target": target, "used_episodes": [],
                         "status": JobStatus.IDLE, "error": None, "items": []})
    return Response(PredictionSerializer(p).data)


def _start_predict(series: Series, data) -> Response:
    req = PredictRequestSerializer(data=data)
    req.is_valid(raise_exception=True)
    target = req.validated_data["target"]

    used = list(range(1, target))
    episodes = {e.number: e for e in series.episodes.filter(number__lt=target)}
    for n in used:
        ep = episodes.get(n)
        if ep is None:
            raise ApiError(f"{n}화가 없습니다")
        if ep.analyze_status != JobStatus.DONE:
            raise ApiError(f"{n}화 분석이 완료되지 않았습니다")

    p, _ = Prediction.objects.update_or_create(
        series=series, target=target,
        defaults={"status": JobStatus.QUEUED, "used_episodes": used, "items": [], "error": ""},
    )
    predict.run(p)  # mock 이면 즉시 done. LLM 은 비동기로 바꿀 예정
    return Response({"target": target, "status": JobStatus.QUEUED}, status=202)


# ---------------------------------------------------------------- episodes

@extend_schema(tags=["episodes"], summary="5. 회차 상세 + 재생 주소",
               responses={200: EpisodeDetailSerializer, 404: ErrorSerializer})
@api_view(["GET"])
def episode_detail(request, pk: int):
    ep = _get_or_404(Episode.objects, pk, EPISODE_NOT_FOUND)
    return Response(EpisodeDetailSerializer(ep).data)


def _analyzed_episode(pk: int) -> Episode:
    """분석 결과가 있는 회차. 회차가 없거나 분석 결과가 없으면 404."""
    ep = _get_or_404(Episode.objects, pk, EPISODE_NOT_FOUND)
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
