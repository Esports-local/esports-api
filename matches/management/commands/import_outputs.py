"""analyzer 결과(outputs/<이름>/work/*.json)를 세트 영상(GameVideo)으로 저장한다. 같은 이름은 덮어쓴다.

    python manage.py import_outputs words_test_1080 --title "Worlds 2026 4강 T1 vs BLG 2세트" --lang ko \\
        --match 32706 --set 2

--match/--set 을 주면 그 세트(MatchGame)에 연결하고, 화면 OCR 로 읽은 팀(블루/레드)과
선수 이름(진영·포지션)을 세트에 채운다 (op.gg 페이지에 없는 정보). 챔피언은 건드리지 않는다.
outputs 폴더는 ANALYZER_OUTPUTS (compose 에서 ../esports-analyzer/outputs 를 /outputs 로 붙임).
"""

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from matches.models import AnalyzeStatus, GamePlayer, GameVideo, MatchGame
from matches.screen import static_values

STAGES = ["preprocess", "segments", "roi_ocr", "asr", "translate", "evaluate"]


class Command(BaseCommand):
    help = "analyzer 결과 폴더를 세트 영상으로 저장한다"

    def add_arguments(self, parser):
        parser.add_argument("work_name", help="analyzer outputs/<이름>")
        parser.add_argument("--title", help="영상 이름 (없으면 work_name)")
        parser.add_argument("--lang", default="ko", help="해설 언어 ko | en")
        parser.add_argument("--match", type=int, help="op.gg 경기 번호 (import_match 로 먼저 저장)")
        parser.add_argument("--set", type=int, dest="set_number", help="세트 번호")
        parser.add_argument("--outputs-dir", default=os.environ.get("ANALYZER_OUTPUTS", "/outputs"))

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


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@transaction.atomic
def save_video(work: Path, work_name: str, title: str, lang: str, game: MatchGame | None) -> GameVideo:
    results = {s: d for s in STAGES if (d := _read(work / f"{s}.json")) is not None}
    pre = (results.get("preprocess") or {}).get("result") or {}
    video, _ = GameVideo.objects.update_or_create(
        work_name=work_name,
        defaults={"title": title, "language": lang, "game": game, "duration": pre.get("duration_sec"),
                  "run_log": _read(work / "run_log.json") or [], "results": results,
                  "analyze_status": AnalyzeStatus.DONE if results else AnalyzeStatus.PENDING})
    if game and "roi_ocr" in results:
        fill_game_from_screen(game, results["roi_ocr"]["result"]["runs"])
    return video


def fill_game_from_screen(game: MatchGame, runs: list[dict]) -> None:
    """화면에서 읽은 팀 약칭으로 블루/레드를 정하고, 선수 이름을 진영·포지션별로 저장한다."""
    statics = static_values(runs)
    teams = {t.acronym.lower(): t for t in (game.match.home_team, game.match.away_team)}
    shown = statics.get("team", {})
    blue, red = teams.get(shown.get("blue", "").lower()), teams.get(shown.get("red", "").lower())
    if blue and red and blue != red:
        game.blue_team, game.red_team = blue, red
        game.save(update_fields=["blue_team", "red_team"])
    for slot, name in statics.get("player_name", {}).items():
        side, _, role = slot.partition("_")
        if side in ("blue", "red") and role:
            GamePlayer.objects.update_or_create(game=game, side=side, role=role, defaults={"name": name})
