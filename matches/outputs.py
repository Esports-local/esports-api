"""analyzer 결과 폴더(outputs/<이름>/work/*.json)를 GameVideo 로 저장한다."""

import json
import os
from pathlib import Path

from django.db import transaction

from matches.models import AnalyzeStatus, GamePlayer, GameVideo, MatchGame
from matches.screen import static_values

STAGES = ["preprocess", "segments", "roi_ocr", "asr", "translate", "evaluate"]
OUTPUTS_ROOT = Path(os.environ.get("ANALYZER_OUTPUTS_IN_CONTAINER", "/outputs"))


def work_dir(work_name: str) -> Path:
    return OUTPUTS_ROOT / work_name / "work"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@transaction.atomic
def save_video(work: Path, work_name: str, title: str, lang: str, game: MatchGame | None,
               **extra) -> GameVideo:
    """결과 JSON 을 모두 읽어 저장한다 (같은 work_name 은 덮어씀). extra 는 GameVideo 필드 (video_name 등)."""
    results = {s: d for s in STAGES if (d := _read(work / f"{s}.json")) is not None}
    pre = (results.get("preprocess") or {}).get("result") or {}
    video, _ = GameVideo.objects.update_or_create(
        work_name=work_name,
        defaults={"title": title, "language": lang, "game": game, "duration": pre.get("duration_sec"),
                  "run_log": _read(work / "run_log.json") or [], "results": results,
                  "analyze_status": AnalyzeStatus.DONE if results else AnalyzeStatus.PENDING, **extra})
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
