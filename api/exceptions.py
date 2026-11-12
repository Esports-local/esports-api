"""에러 응답을 {"error": "메시지"} 하나로 맞춘다."""

from django.http import Http404
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


def first_message(detail) -> str:
    """DRF 검증 에러(dict/list 중첩)에서 사람이 읽을 첫 메시지를 뽑는다.

    필드 에러는 "필드: 메시지" 로 만들되, 메시지에 이미 필드 이름이 있으면 그대로 둔다.
    """
    if isinstance(detail, dict):
        if not detail:
            return "잘못된 요청입니다"
        key, value = next(iter(detail.items()))
        msg = first_message(value)
        if key in ("detail", "non_field_errors") or str(key) in msg:
            return msg
        return f"{key}: {msg}"
    if isinstance(detail, list):
        return first_message(detail[0]) if detail else "잘못된 요청입니다"
    return str(detail)


def handler(exc, context):
    if isinstance(exc, ApiError):
        return Response({"error": exc.message}, status=exc.status)
    if isinstance(exc, Http404):
        return Response({"error": str(exc) or "찾을 수 없습니다"}, status=404)
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {"error": first_message(response.data)}
    return response


def get_or_404(queryset, pk: int, message: str):
    """pk 로 하나를 찾고, 없으면 {"error": message} 404."""
    obj = queryset.filter(pk=pk).first()
    if obj is None:
        raise Http404(message)
    return obj
