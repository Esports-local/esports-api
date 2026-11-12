"""analyzer 결과(outputs/<이름>/work/*.json)를 세트 영상(GameVideo)으로 저장한다. 같은 이름은 덮어쓴다.

    python manage.py import_outputs words_test_1080 --title "Worlds 2026 4강 T1 vs BLG 2세트" --lang ko \\
        --match 32706 --set 2

--match/--set 을 주면 그 세트(MatchGame)에 연결하고, 화면 OCR 로 읽은 팀(블루/레드)과
선수 이름(진영·포지션)을 세트에 채운다 (op.gg 페이지에 없는 정보). 챔피언은 건드리지 않는다.
outputs 폴더는 컨테이너의 /outputs (compose 가 ANALYZER_OUTPUTS 호스트 폴더를 붙임).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from matches.models import MatchGame
from matches.outputs import save_video


class Command(BaseCommand):
    help = "analyzer 결과 폴더를 세트 영상으로 저장한다"

    def add_arguments(self, parser):
        parser.add_argument("work_name", help="analyzer outputs/<이름>")
        parser.add_argument("--title", help="영상 이름 (없으면 work_name)")
        parser.add_argument("--lang", default="ko", help="해설 언어 ko | en")
        parser.add_argument("--match", type=int, help="op.gg 경기 번호 (import_match 로 먼저 저장)")
        parser.add_argument("--set", type=int, dest="set_number", help="세트 번호")
        parser.add_argument("--outputs-dir", default="/outputs", help="컨테이너 안 analyzer outputs 경로")

    def handle(self, *args, work_name, title, lang, match, set_number, outputs_dir, **options):
        work = Path(outputs_dir) / work_name / "work"
        if not work.is_dir():
            raise CommandError(f"결과 폴더가 없습니다: {work}")
        game = None
        if match or set_number:
            game = MatchGame.objects.filter(match__opgg_id=match, number=set_number).first()
            if game is None:
                raise CommandError(f"경기 {match} {set_number}세트가 없습니다. import_match {match} 를 먼저 하세요")
        video = save_video(work, work_name, title or work_name, lang, game)
        stages = ", ".join(video.results) or "없음"
        self.stdout.write(self.style.SUCCESS(f"{video.id} {video.title} | 단계 {stages} | 세트 {game or '-'}"))
