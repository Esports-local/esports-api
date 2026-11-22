"""analyzer 결과 저장(header 포함)과 2번 응답의 경기 정보. api 는 op.gg 를 부르지 않는다."""

import json
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from matches import outputs
from matches.models import GameVideo

# analyzer work/header.json 의 result (pipeline/header.py)
HEADER = {
    "match": {"opgg_id": 32706, "name": "Semifinal 1: BLG vs T1", "league": "Worlds", "stage": "Playoffs",
              "year": 2026, "format": "BO5", "set": 2, "patch": "16.22.1", "begin_at": "2026-11-08T22:07:29.000Z",
              "score": {"BLG": 3, "T1": 1}, "source_url": "https://esports.op.gg/matches/32706",
              "video_url": "https://youtu.be/a"},
    "teams": {"blue": {"name": "T1", "full": "T1", "opgg_id": 385},
              "red": {"name": "BLG", "full": "Bilibili Gaming", "opgg_id": 632}},
    "players": [
        {"side": "blue", "team": "T1", "role": "support", "name": "Keria",
         "champion": {"name": "Poppy", "ko": "뽀삐", "skills": {"Q": "망치 강타"}}},
        {"side": "red", "team": "BLG", "role": "jungle", "name": "XUN",
         "champion": {"name": "Qiyana", "ko": "키아나", "skills": {}}},
    ],
    "bans": {"blue": [], "red": []}, "result": {"winner": "blue", "length_sec": 1935},
    "series": {"score_before": {"BLG": 1, "T1": 0}, "previous": [], "fearless": True, "fearless_unavailable": []},
    "source": {"opgg": "https://esports.op.gg/matches/32706", "ddragon_version": "16.22.1"}, "error": None,
}


def stage(name, result):
    return {"schema_version": 1, "stage": name, "episode": "t", "params": {}, "result": result}


class SaveVideoTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / "game_1080" / "work"
        self.work.mkdir(parents=True)

    def write(self, name, result):
        (self.work / f"{name}.json").write_text(json.dumps(stage(name, result), ensure_ascii=False), encoding="utf-8")

    def test_header_saved_as_is(self):
        self.write("header", HEADER)
        self.write("preprocess", {"duration_sec": 60.0})
        v = outputs.save_video(self.work, "game_1080", "t", "ko")
        self.assertEqual((v.header, v.duration, sorted(v.results)), (HEADER, 60.0, ["header", "preprocess"]))

        self.write("header", {**{k: {} for k in HEADER}, "players": [], "error": "ConnectError: op.gg"})
        v = outputs.save_video(self.work, "game_1080", "t", "ko")
        self.assertEqual(v.header, HEADER)  # analyzer 가 op.gg 에서 못 받으면 이전 헤더를 둔다

    def test_import_outputs_records_match_set(self):
        self.write("header", HEADER)
        call_command("import_outputs", "game_1080", "--match", "32706", "--set", "2",
                     "--outputs-dir", self.tmp.name, stdout=open("/dev/null", "w"))
        v = GameVideo.objects.get(work_name="game_1080")
        self.assertEqual((v.opgg_match, v.set_number, v.header["match"]["set"]), (32706, 2, 2))

    def test_import_outputs_video_name(self):
        out = open("/dev/null", "w")
        call_command("import_outputs", "game_1080", "--video", "game.mp4", "--outputs-dir", self.tmp.name, stdout=out)
        v = GameVideo.objects.get(work_name="game_1080")
        self.assertEqual((v.playback_name, v.video_name), ("game.mp4", ""))  # 재분석 대상(video_name)은 그대로
        call_command("import_outputs", "game_1080", "--outputs-dir", self.tmp.name, stdout=out)
        self.assertEqual(GameVideo.objects.get(work_name="game_1080").playback_name, "game.mp4")  # 안 주면 그대로
        with self.assertRaises(CommandError):
            call_command("import_outputs", "game_1080", "--video", "../x.mp4", "--outputs-dir", self.tmp.name, stdout=out)


class MatchInfoTest(TestCase):
    def test_detail_match_from_header(self):
        v = GameVideo.objects.create(title="t", work_name="t", header=HEADER)
        d = self.client.get(f"/games/{v.id}").json()
        m = d["match"]
        self.assertEqual((m["tournament"], m["game"], m["score"], m["winner"], m["video_url"]),
                         ("Worlds 2026", 2, {"BLG": 3, "T1": 1}, "blue", "https://youtu.be/a"))
        self.assertEqual(m["blue"], {"team": "T1", "players": {
            "support": {"name": "Keria", "champion": "Poppy", "champion_ko": "뽀삐"}}})
        self.assertEqual(self.client.get("/games").json()[0]["teams"], {"blue": "T1", "red": "BLG"})

    def test_no_header(self):
        v = GameVideo.objects.create(title="t", work_name="t")
        self.assertIsNone(self.client.get(f"/games/{v.id}").json()["match"])
