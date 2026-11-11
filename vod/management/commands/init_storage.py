import time

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from vod import storage


class Command(BaseCommand):
    help = "버킷(S3_BUCKET)이 없으면 만들고 hls/ 공개 읽기 정책을 건다. 저장소가 뜰 때까지 잠시 재시도한다."

    def add_arguments(self, parser):
        parser.add_argument("--wait", type=float, default=30, help="저장소 대기 최대 초 (기본 30)")

    def handle(self, *args, wait, **options):
        deadline = time.monotonic() + wait
        while True:
            try:
                created = storage.ensure_bucket()
                break
            except (BotoCoreError, ClientError) as e:
                if time.monotonic() > deadline:
                    raise CommandError(f"저장소 연결 실패 ({settings.S3_ENDPOINT_URL}): {e}")
                time.sleep(1)
        self.stdout.write(f"bucket {settings.S3_BUCKET}: {'생성' if created else '이미 있음'}")

        try:
            storage.ensure_public_read()
            self.stdout.write(f"공개 읽기: {', '.join(storage.PUBLIC_PREFIXES)}")
        except (BotoCoreError, ClientError) as e:  # 정책 권한이 없는 외부 저장소
            self.stderr.write(f"[warn] 공개 읽기 정책 실패 → HLS 재생이 막힐 수 있음: {e}")
