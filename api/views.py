"""공통 엔드포인트 (/health)."""

from django.conf import settings
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as s
from rest_framework.decorators import api_view
from rest_framework.response import Response

from config import storage


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
