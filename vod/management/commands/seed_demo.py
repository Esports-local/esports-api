"""Swagger·ui 개발용 데모 데이터. 크롤링(TMDB) 명령이 생기기 전까지 쓴다.

    python manage.py seed_demo           # 작품 1개, 회차 12개(1~10화 분석 완료), 등장인물 3명
    python manage.py seed_demo --reset   # 데모 작품을 지우고 다시 만든다

분석 결과는 esports-analyzer 샘플(episode.json) 모양을 흉내 낸 최소 JSON 이다.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.db import transaction

from vod.models import Character, Episode, JobStatus, Series

DEMO_TMDB_ID = 999999  # 실제 TMDB 와 겹치지 않는 번호


def _analysis(n: int) -> dict:
    return {
        "schema_version": 1, "episode": f"ep{n:02d}", "duration_sec": 3600.0,
        "scenes": [
            {"id": 1, "start_sec": 0.0, "end_sec": 95.5, "type": "talk",
             "summary": f"{n}화 도입: 민지와 준호가 사무실에서 대화한다", "keywords": ["사무실"],
             "black_before": False, "faces": ["F1", "F2"],
             "lines": [{"start_sec": 3.2, "end_sec": 5.8, "speaker": "S1", "text": "서류 어디 있어요?"}]},
            {"id": 2, "start_sec": 96.0, "end_sec": 180.0, "type": "action",
             "summary": f"{n}화: 준호가 서류를 숨긴다", "keywords": ["서류"],
             "black_before": True, "faces": ["F2"], "lines": []},
        ],
        "speakers": [], "faces": [],
    }


class Command(BaseCommand):
    help = "Swagger·ui 개발용 데모 작품을 만든다."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="데모 작품을 지우고 다시 만든다")

    @transaction.atomic
    def handle(self, *args, reset, **options):
        if reset:
            Series.objects.filter(tmdb_id=DEMO_TMDB_ID).delete()
        if Series.objects.filter(tmdb_id=DEMO_TMDB_ID).exists():
            self.stdout.write("데모 작품이 이미 있습니다 (--reset 으로 다시 만들기)")
            return

        series = Series.objects.create(
            tmdb_id=DEMO_TMDB_ID, title="데모 드라마", synopsis="회사에서 사라진 서류를 둘러싼 이야기",
            first_air_date=dt.date(2026, 1, 10), episode_count=12,
            genres=["드라마", "미스터리"], crew=[{"name": "작가 이름", "job": "Writer"}],
        )
        for n in range(1, 13):
            analyzed = n <= 10
            Episode.objects.create(
                series=series, number=n, title=f"{n}화", synopsis=f"{n}화 줄거리",
                air_date=dt.date(2026, 1, 10) + dt.timedelta(weeks=n - 1),
                analyze_status=JobStatus.DONE if analyzed else JobStatus.IDLE,
                duration=3600.0 if analyzed else None,
                analysis=_analysis(n) if analyzed else None,
                schema_version=1 if analyzed else None,
            )
        for i, (name, actor, aliases) in enumerate([
            ("민지", "배우 A", ["김 대리"]), ("준호", "배우 B", []), ("수아", "배우 C", ["팀장님"]),
        ]):
            Character.objects.create(series=series, name=name, actor=actor, aliases=aliases, order=i)
        self.stdout.write(self.style.SUCCESS(f"데모 작품 생성: id={series.id} (회차 12, 1~10화 분석 완료)"))
