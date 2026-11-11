from django.conf import settings
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from vod import storage


@extend_schema(responses={200: dict, 503: dict})
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
