import time

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from vod import storage


class Command(BaseCommand):
    help = "MinIO 버킷(S3_BUCKET)이 없으면 만든다. MinIO 가 뜰 때까지 잠시 재시도한다."

    def add_arguments(self, parser):
        parser.add_argument("--wait", type=float, default=30, help="MinIO 대기 최대 초 (기본 30)")

    def handle(self, *args, wait, **options):
        deadline = time.monotonic() + wait
        while True:
            try:
                created = storage.ensure_bucket()
                break
            except (BotoCoreError, ClientError) as e:
                if time.monotonic() > deadline:
                    raise CommandError(f"MinIO 연결 실패 ({settings.S3_ENDPOINT_URL}): {e}")
                time.sleep(1)
        state = "생성" if created else "이미 있음"
        self.stdout.write(f"bucket {settings.S3_BUCKET}: {state}")
