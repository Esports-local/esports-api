"""analyzer 결과 폴더(outputs/<이름>/work/*.json)를 GameVideo 로 저장한다."""

import json
import os
from pathlib import Path

from django.db import transaction

from matches.header import refresh_header, refresh_match_headers
from matches.models import AnalyzeStatus, GamePlayer, GameVideo, MatchGame
from matches.screen import static_values

STAGES = ["preprocess", "segments", "roi_ocr", "asr", "translate", "timeline", "evaluate"]
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
    if game:  # 이 세트가 바뀌면 뒤 세트 헤더(이전 세트 밴픽·스코어)도 바뀐다
        refresh_match_headers(game)
        video.refresh_from_db(fields=["header"])
    else:
        refresh_header(video)
    return video


def fill_game_from_screen(game: MatchGame, runs: list[dict]) -> None:
    """화면 OCR 로 블루/레드 팀과 진영·포지션별 선수 이름을 채운다.

    op.gg 세트 정보가 있는 세트(챔피언이 채워진 선수가 있음)의 팀과, 챔피언이 있는 선수(op.gg 값)는 덮어쓰지 않는다.
    예전 OCR 값은 새 OCR 값으로 바뀐다 (분석을 다시 돌리면 고쳐짐)."""
    statics = static_values(runs)
    teams = {t.acronym.lower(): t for t in (game.match.home_team, game.match.away_team)}
    shown = statics.get("team", {})
    blue, red = teams.get(shown.get("blue", "").lower()), teams.get(shown.get("red", "").lower())
    if blue and red and blue != red and not game.has_opgg_lineup():
        game.blue_team, game.red_team = blue, red
        game.save(update_fields=["blue_team", "red_team"])
    for slot, name in statics.get("player_name", {}).items():
        side, _, role = slot.partition("_")
        if side in ("blue", "red") and role:
            GamePlayer.objects.filter(game=game, side=side, role=role, champion="").update(name=name)
            if not GamePlayer.objects.filter(game=game, side=side, role=role).exists():
                GamePlayer.objects.create(game=game, side=side, role=role, name=name)
