"""ui → api 엔드포인트. 스펙은 스펙 시트(호출 목록, series, episodes 탭) 기준."""

from django.conf import settings
from django.db import connection
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as s
from rest_framework.decorators import api_view
from rest_framework.response import Response

from vod import predict, storage
from vod.exceptions import ApiError
from vod.models import Episode, JobStatus, Prediction, Series
from vod.serializers import (
    EpisodeDetailSerializer,
    ErrorSerializer,
    PredictAcceptedSerializer,
    PredictionSerializer,
    PredictRequestSerializer,
    SeriesDetailSerializer,
    SeriesListSerializer,
)


def _get_series(pk: int) -> Series:
    try:
        return Series.objects.get(pk=pk)
    except Series.DoesNotExist:
        raise Http404("작품을 찾을 수 없습니다")


# ---------------------------------------------------------------- 상태

@extend_schema(tags=["health"], responses={200: inline_serializer("Health", {
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
    series = Series.objects.prefetch_related("episodes", "characters").filter(pk=pk).first()
    if series is None:
        raise Http404("작품을 찾을 수 없습니다")
    return Response(SeriesDetailSerializer(series).data)


@extend_schema(methods=["POST"], tags=["series"], summary="3. target 회차 예측 시작",
               request=PredictRequestSerializer,
               responses={202: PredictAcceptedSerializer, 400: ErrorSerializer, 404: ErrorSerializer})
@extend_schema(methods=["GET"], tags=["series"], summary="4. 예측 상태 + 결과",
               parameters=[OpenApiParameter("target", int, required=True, description="예측한 회차 번호")],
               responses={200: PredictionSerializer, 400: ErrorSerializer, 404: ErrorSerializer})
@api_view(["GET", "POST"])
def series_predict(request, pk: int):
    series = _get_series(pk)
    if request.method == "POST":
        return _start_predict(series, request.data)

    raw = request.query_params.get("target")
    if not raw:
        raise ApiError("target 이 필요합니다")
    try:
        target = int(raw)
    except ValueError:
        raise ApiError("target 은 정수여야 합니다")
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
    try:
        ep = Episode.objects.get(pk=pk)
    except Episode.DoesNotExist:
        raise Http404("회차를 찾을 수 없습니다")
    return Response(EpisodeDetailSerializer(ep).data)
