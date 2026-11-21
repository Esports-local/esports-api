"""analyzer 결과(outputs/<이름>/work/*.json)를 세트 영상(GameVideo)으로 저장한다. 같은 이름은 덮어쓴다.

    python manage.py import_outputs words_test_1080 --title "Worlds 2026 4강 T1 vs BLG 2세트" --lang ko \\
        --match 32706 --set 2

경기 정보는 analyzer header 단계 결과(work/header.json)에서 온다. api 는 op.gg 를 부르지 않는다.
--match/--set 은 기록만 해 둔다 (화면에서 header 단계를 다시 실행할 때 analyzer 에 넘김).
outputs 폴더는 컨테이너의 /outputs (compose 가 ANALYZER_OUTPUTS 호스트 폴더를 붙임).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from matches.outputs import save_video


class Command(BaseCommand):
    help = "analyzer 결과 폴더를 세트 영상으로 저장한다"

    def add_arguments(self, parser):
        parser.add_argument("work_name", help="analyzer outputs/<이름>")
        parser.add_argument("--title", help="영상 이름 (없으면 work_name)")
        parser.add_argument("--lang", default="ko", help="해설 언어 ko | en")
        parser.add_argument("--match", type=int, help="op.gg 경기 번호")
        parser.add_argument("--set", type=int, dest="set_number", help="세트 번호")
        parser.add_argument("--outputs-dir", default="/outputs", help="컨테이너 안 analyzer outputs 경로")

    def handle(self, *args, work_name, title, lang, match, set_number, outputs_dir, **options):
        work = Path(outputs_dir) / work_name / "work"
        if not work.is_dir():
            raise CommandError(f"결과 폴더가 없습니다: {work}")
        if bool(match) != bool(set_number):
            raise CommandError("--match 와 --set 은 같이 줍니다")
        extra = {"opgg_match": match, "set_number": set_number} if match else {}
        video = save_video(work, work_name, title or work_name, lang, **extra)
        stages = ", ".join(video.results) or "없음"
        has_header = "있음" if video.header else "없음 (header 단계를 돌리면 생김)"
        self.stdout.write(self.style.SUCCESS(f"{video.id} {video.title} | 단계 {stages} | 경기 정보 {has_header}"))
