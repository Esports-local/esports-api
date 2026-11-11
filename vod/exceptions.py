"""에러 응답을 {"error": "메시지"} 하나로 맞춘다."""

from django.http import Http404
from rest_framework.views import exception_handler


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


def _first_message(detail) -> str:
    """DRF 검증 에러(dict/list 중첩)에서 사람이 읽을 첫 메시지를 뽑는다."""
    if isinstance(detail, dict):
        key, value = next(iter(detail.items()))
        msg = _first_message(value)
        return msg if key in ("detail", "non_field_errors") else f"{key}: {msg}"
    if isinstance(detail, list) and detail:
        return _first_message(detail[0])
    return str(detail)


def handler(exc, context):
    from rest_framework.response import Response

    if isinstance(exc, ApiError):
        return Response({"error": exc.message}, status=exc.status)
    if isinstance(exc, Http404):
        return Response({"error": str(exc) or "찾을 수 없습니다"}, status=404)
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {"error": _first_message(response.data)}
    return response
