"""영상 등록·분석 실행 (analyzer 호출은 가짜로 바꾼다)."""

import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from api.exceptions import ApiError
from api.games import jobs
from matches import outputs
from matches.models import GameVideo

SOURCES = [
    {"name": "game_1080.mp4", "size_bytes": 1, "duration_sec": 60.0, "width": 1920, "height": 1080,
     "has_audio": True, "selectable": True, "reason": None},
    {"name": "raw.mov", "size_bytes": 1, "duration_sec": 60.0, "width": 3420, "height": 2214,
     "has_audio": True, "selectable": False, "reason": "3420x2214 (1920x1080 만 가능)"},
]


class GameJobTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        work = Path(self.tmp.name) / "game_1080" / "work"
        work.mkdir(parents=True)
        (work / "preprocess.json").write_text(json.dumps({"stage": "preprocess", "result": {"duration_sec": 60.0}}))
        patches = [mock.patch("api.games.analyzer.list_videos", return_value=SOURCES),
                   mock.patch("api.games.analyzer.start_job", return_value={"status": "running"}),
                   # 실제 analyzer 에 묻지 않게: 기본은 "진행 중"
                   mock.patch("api.games.analyzer.get_job", return_value={"status": "running", "current_stage": None,
                                                                        "stages": [], "elapsed_sec": 0.0}),
                   mock.patch.object(outputs, "OUTPUTS_ROOT", Path(self.tmp.name))]
        self.mocks = [p.start() for p in patches]
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.tmp.cleanup)

    def test_sources_and_reject_raw(self):
        rows = self.client.get("/sources").json()
        self.assertEqual([(r["name"], r["selectable"], r["game_id"]) for r in rows],
                         [("game_1080.mp4", True, None), ("raw.mov", False, None)])
        r = self.client.post("/games", {"video": "raw.mov"}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("고를 수 없는 영상", r.json()["error"])

    def test_create_with_match_runs_header_first(self):
        body = {"video": "game_1080.mp4", "match": 32706, "set": 2, "stages": ["asr"]}
        r = self.client.post("/games", body, content_type="application/json")
        self.assertEqual(r.status_code, 201)
        v = GameVideo.objects.get()
        self.assertEqual((v.opgg_match, v.set_number), (32706, 2))
        args = self.mocks[1].call_args.args
        self.assertEqual((args[2], args[3]), (["header", "asr"], {"header": {"match": 32706, "set": 2}}))
        GameVideo.objects.update(analyze_status="done")
        bad = self.client.post("/games", {**body, "set": "x"}, content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_header_dropped_without_match(self):
        v = GameVideo.objects.create(title="t", work_name="game_1080", analyze_status="done")
        r = self.client.post(f"/games/{v.id}/analyze", {"stages": ["header", "asr"]}, content_type="application/json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(self.mocks[1].call_args.args[2], ["asr"])  # 경기·세트를 모르면 header 는 뺀다
        GameVideo.objects.filter(pk=v.pk).update(analyze_status="done")
        r = self.client.post(f"/games/{v.id}/analyze", {"stages": ["header"]}, content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_create_start_and_finish(self):
        r = self.client.post("/games", {"video": "game_1080.mp4", "title": "테스트", "language": "ko"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 201)
        v = GameVideo.objects.get(work_name="game_1080")
        self.assertEqual((v.title, v.video_name, v.analyze_status), ("테스트", "game_1080.mp4", "running"))
        args = self.mocks[1].call_args.args
        self.assertEqual((args[1], args[2]), ("game_1080.mp4", ["preprocess", "segments", "roi_ocr", "asr", "timeline", "context", "shorts"]))

        # 다시 시작하면 409
        r = self.client.post(f"/games/{v.id}/analyze", {"stages": ["asr"]}, content_type="application/json")
        self.assertEqual(r.status_code, 409)

        with mock.patch("api.games.analyzer.get_job", return_value={"status": "running", "current_stage": "asr",
                                                                  "stages": ["asr"], "elapsed_sec": 3.0}):
            d = self.client.get(f"/games/{v.id}").json()
        self.assertEqual((d["analyze_status"], d["progress"]["current_stage"]), ("running", "asr"))

        with mock.patch("api.games.analyzer.get_job", return_value={"status": "succeeded"}):
            d = self.client.get(f"/games/{v.id}").json()
        self.assertEqual((d["analyze_status"], d["duration_sec"], d["error"]), ("done", 60.0, None))

    def test_failed_and_analyzer_restart(self):
        v = GameVideo.objects.create(title="t", work_name="game_1080", video_name="game_1080.mp4",
                                     analyze_status="running", job_id="j1")
        with mock.patch("api.games.analyzer.get_job", return_value={"status": "failed", "error": "오디오 트랙이 없어"}):
            d = self.client.get(f"/games/{v.id}").json()
        self.assertEqual((d["analyze_status"], d["error"]), ("failed", "오디오 트랙이 없어"))

        GameVideo.objects.filter(pk=v.pk).update(analyze_status="running")
        with mock.patch("api.games.analyzer.get_job", side_effect=ApiError("작업을 찾을 수 없습니다", 404)):
            d = self.client.get(f"/games/{v.id}").json()
        self.assertEqual(d["analyze_status"], "failed")
        self.assertIn("다시 시작", d["error"])

    def test_analyze_stages(self):
        v = GameVideo.objects.create(title="t", work_name="game_1080", analyze_status="done")
        r = self.client.post(f"/games/{v.id}/analyze", {"stages": ["timeline"]}, content_type="application/json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(self.mocks[1].call_args.args[2], ["timeline"])
        self.assertEqual(GameVideo.objects.get(pk=v.pk).video_name, "game_1080.mp4")  # work_name 으로 찾음
        GameVideo.objects.filter(pk=v.pk).update(analyze_status="done")
        bad = self.client.post(f"/games/{v.id}/analyze", {"stages": ["translate"]}, content_type="application/json")
        self.assertEqual(bad.status_code, 400)  # 번역은 실행하지 않는다
        self.assertEqual(self.client.get(f"/games/{v.id}/estimate").status_code, 404)

    def test_source_for_missing(self):
        v = GameVideo.objects.create(title="t", work_name="없는영상")
        with self.assertRaises(ApiError):
            jobs.source_for(v)
