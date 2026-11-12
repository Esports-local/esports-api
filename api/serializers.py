"""엔드포인트 공통 응답 모양. 엔드포인트별 모양은 각 폴더의 serializers.py."""

from rest_framework import serializers


def blank_to_none(value):
    return value or None


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()
