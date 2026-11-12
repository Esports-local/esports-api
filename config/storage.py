"""MinIO(S3 호환) 접근.

- 내부 클라이언트: api 컨테이너 → MinIO (S3_ENDPOINT_URL). 업로드·조회·버킷 관리
- 공개 클라이언트: presigned URL 생성 전용 (S3_PUBLIC_ENDPOINT_URL).
  서명에 host 가 포함되므로 브라우저가 접속할 주소로 서명해야 한다.

공개 범위
- hls/ 는 공개 읽기 (버킷 정책). master.m3u8 안의 index.m3u8·ts 는 상대 경로로 요청되어
  서명을 붙일 수 없으므로, 재생 주소는 서명 없는 public_url 을 쓴다.
- raw/(원본), analysis/(분석 결과) 는 비공개. 필요하면 presigned_url.

DB에는 key 만 저장한다 (예: hls/12/master.m3u8). 세트 영상 재생(hls)에 쓸 예정.
"""

import json
from functools import cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings

PUBLIC_PREFIXES = ("hls/",)

# 저장소가 꺼져 있거나 막혀 있을 때 오래 멈추지 않도록 짧게 둔다
_CONFIG = Config(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    connect_timeout=3,
    read_timeout=10,
    retries={"max_attempts": 2, "mode": "standard"},
)


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=_CONFIG,
    )


@cache
def client():
    """내부 접근용 S3 클라이언트."""
    return _client(settings.S3_ENDPOINT_URL)


@cache
def public_client():
    """presigned URL 생성용 S3 클라이언트 (네트워크 접속은 하지 않음)."""
    return _client(settings.S3_PUBLIC_ENDPOINT_URL)


def _error_code(e: ClientError) -> str:
    return str(e.response.get("Error", {}).get("Code", ""))


def ensure_bucket() -> bool:
    """버킷이 없으면 만든다. 새로 만들었으면 True.

    list_buckets(계정 전체 권한)가 아니라 head_bucket 으로 확인해서,
    버킷 하나만 허용된 외부 저장소 키에서도 동작한다.
    """
    s3, bucket = client(), settings.S3_BUCKET
    try:
        s3.head_bucket(Bucket=bucket)
        return False
    except ClientError as e:
        if _error_code(e) not in ("404", "NoSuchBucket", "NotFound"):
            raise
    try:
        s3.create_bucket(Bucket=bucket)
    except ClientError as e:  # 동시에 만들어진 경우
        if _error_code(e) not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise
        return False
    return True


def ensure_public_read() -> None:
    """PUBLIC_PREFIXES 아래 객체를 누구나 읽을 수 있게 버킷 정책을 건다 (HLS 재생용)."""
    bucket = settings.S3_BUCKET
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicReadHls",
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{bucket}/{p}*" for p in PUBLIC_PREFIXES],
        }],
    }
    client().put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))


def public_url(key: str | None) -> str | None:
    """공개 경로(hls/)의 서명 없는 주소. key 가 없으면 None."""
    if not key:
        return None
    if not key.startswith(PUBLIC_PREFIXES):
        raise ValueError(f"공개 경로가 아님: {key}")
    return f"{settings.S3_PUBLIC_ENDPOINT_URL.rstrip('/')}/{settings.S3_BUCKET}/{key}"


def presigned_url(key: str | None, expires: int | None = None) -> str | None:
    """비공개 객체의 presigned GET URL. key 가 없으면 None."""
    if not key:
        return None
    return public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key},
        ExpiresIn=expires or settings.S3_PRESIGN_EXPIRES,
    )
