"""/series 엔드포인트 (드라마 스펙 1~4번)."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.exceptions import ApiError, get_or_404
from api.serializers import ErrorSerializer
from api.series import predict
from api.series.serializers import (
    PredictAcceptedSerializer,
    PredictionSerializer,
    PredictRequestSerializer,
    SeriesDetailSerializer,
    SeriesListSerializer,
)
from vod.models import JobStatus, Prediction, Series

SERIES_NOT_FOUND = "작품을 찾을 수 없습니다"


@extend_schema(tags=["series"], summary="1. 작품 목록", responses=SeriesListSerializer(many=True))
@api_view(["GET"])
def series_list(request):
    return Response(SeriesListSerializer(Series.objects.all(), many=True).data)


@extend_schema(tags=["series"], summary="2. 작품 상세 + 회차 목록 + 등장인물",
               responses={200: SeriesDetailSerializer, 404: ErrorSerializer})
@api_view(["GET"])
def series_detail(request, pk: int):
    series = get_or_404(Series.objects.prefetch_related("episodes", "characters"), pk, SERIES_NOT_FOUND)
    return Response(SeriesDetailSerializer(series).data)


@extend_schema(methods=["POST"], tags=["series"], summary="3. target 회차 예측 시작",
               request=PredictRequestSerializer,
               responses={202: PredictAcceptedSerializer, 400: ErrorSerializer, 404: ErrorSerializer})
@extend_schema(methods=["GET"], tags=["series"], summary="4. 예측 상태 + 결과",
               parameters=[OpenApiParameter("target", int, required=True, description="예측한 회차 번호 (2 이상)")],
               responses={200: PredictionSerializer, 400: ErrorSerializer, 404: ErrorSerializer})
@api_view(["GET", "POST"])
def series_predict(request, pk: int):
    series = get_or_404(Series.objects, pk, SERIES_NOT_FOUND)
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
