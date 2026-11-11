"""MinIO(S3 호환) 접근.

- 내부 클라이언트: api 컨테이너 → MinIO (S3_ENDPOINT_URL). 업로드·조회·버킷 관리
- 공개 클라이언트: presigned URL 생성 전용 (S3_PUBLIC_ENDPOINT_URL).
  서명에 host 가 포함되므로 브라우저가 접속할 주소로 서명해야 한다.

DB에는 key 만 저장한다 (예: hls/12/master.m3u8, analysis/12/episode.json). 구조는 PLAN.md 3장.
"""

from functools import cache

import boto3
from botocore.client import Config
from django.conf import settings


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@cache
def client():
    """내부 접근용 S3 클라이언트."""
    return _client(settings.S3_ENDPOINT_URL)


@cache
def public_client():
    """presigned URL 생성용 S3 클라이언트 (네트워크 접속은 하지 않음)."""
    return _client(settings.S3_PUBLIC_ENDPOINT_URL)


def ensure_bucket() -> bool:
    """버킷이 없으면 만든다. 새로 만들었으면 True."""
    s3 = client()
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if settings.S3_BUCKET in existing:
        return False
    s3.create_bucket(Bucket=settings.S3_BUCKET)
    return True


def presigned_url(key: str | None, expires: int | None = None) -> str | None:
    """key 의 재생/다운로드용 presigned GET URL. key 가 없으면 None."""
    if not key:
        return None
    return public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key},
        ExpiresIn=expires or settings.S3_PRESIGN_EXPIRES,
    )
