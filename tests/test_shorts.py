"""경기 이벤트·숏폼 엔드포인트 (스펙 시트 spec_sheet_lol 14~17번). analyzer·저장소 호출은 바꿔 끼운다."""

from unittest import mock

from django.test import TestCase

from api.exceptions import ApiError
from matches.models import GameVideo, LineReview, Short

EVENTS = [
    {"id": 1, "type": "kill", "team": "blue", "team_name": "T1", "start_sec": 100.0, "end_sec": 100.0,
     "value_before": 0, "value_after": 1, "game_time": "03:23",
     "players": {"killer": ["Doran"], "victims": ["Bin"]}, "line_ids": [1], "evidence": []},
    {"id": 2, "type": "kill", "team": "red", "team_name": "BLG", "start_sec": 105.0, "end_sec": 105.0,
     "value_before": 0, "value_after": 1, "game_time": "03:30",
     "players": {"killer": ["Xun"], "victims": ["Doran"]}, "line_ids": [], "evidence": []},
    {"id": 3, "type": "tower", "team": "red", "team_name": "BLG", "start_sec": 2.0, "end_sec": 4.0,
     "value_before": 0, "value_after": 1, "game_time": None, "players": {}, "line_ids": [], "evidence": []},
]
LINES = [{"id": 1, "start_sec": 97.0, "end_sec": 99.0, "speaker": None, "language": "ko", "text": "캐리아 들어갑니다"},
         {"id": 2, "start_sec": 300.0, "end_sec": 302.0, "speaker": None, "language": "ko", "text": "구간 밖"}]


def stage(name, result, created_at="2026-11-20T00:00:00Z"):
    return {"schema_version": 1, "stage": name, "episode": "t", "created_at": created_at, "params": {}, "result": result}


def analyzer_state(key, status="queued", **kw):
    return {"key": key, "work_name": "t", "status": status, "output": None, "render_sec": None, "error": None, **kw}


@mock.patch("api.shorts.shorts.jobs.source_for", return_value="t.mp4")
class ShortsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.v = GameVideo.objects.create(
            title="세트", work_name="t", duration=200.0, analyze_status="done",
            results={"asr": stage("asr", {"lines": LINES}),
                     "timeline": stage("timeline", {"events": EVENTS, "teams": {"blue": "T1", "red": "BLG"}})})

    def post(self, body):
        return self.client.post(f"/games/{self.v.id}/shorts", body, content_type="application/json")

    def test_events_filter_and_clip(self, _src):
        events = self.client.get(f"/games/{self.v.id}/events?type=kill&player=doran").json()["events"]
        self.assertEqual([e["id"] for e in events], [1, 2])
        self.assertEqual(events[0]["clip"], {"start_sec": 94.0, "end_sec": 104.0})
        tower = self.client.get(f"/games/{self.v.id}/events?type=tower").json()["events"][0]
        self.assertEqual(tower["clip"]["start_sec"], 0.0)  # 영상 시작 앞으로 나가지 않음
        self.assertEqual(self.client.get(f"/games/{self.v.id}/events?type=dragon").status_code, 400)
        empty = GameVideo.objects.create(title="빈", work_name="empty")
        self.assertEqual(self.client.get(f"/games/{empty.id}/events").status_code, 404)

    def test_range_game_renders_from_playback_file(self, src):
        part = GameVideo.objects.create(title="구간", work_name="t_900-1500s", playback_name="t.mp4",
                                        results=self.v.results)
        with mock.patch("api.shorts.shorts.analyzer.create_short", side_effect=lambda key, *a: analyzer_state(key)) as cs:
            res = self.client.post(f"/games/{part.id}/shorts", {"event_ids": [1]}, content_type="application/json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(cs.call_args.args[1], "t.mp4")  # 재분석용 video_name 이 비어도 원본 파일로 렌더
        src.assert_not_called()

    def test_create_merges_and_reuses(self, _src):
        LineReview.objects.create(video=self.v, line_id=1, asr_text="캐리아 들어갑니다", text="케리아 들어갑니다")
        with mock.patch("api.shorts.shorts.analyzer.create_short", side_effect=lambda key, *a: analyzer_state(key)) as cs:
            res = self.post({"event_ids": [2, 1]})
            self.assertEqual(res.status_code, 201)
            body = res.json()
            self.assertEqual(body["segments"], [{"start_sec": 94.0, "end_sec": 109.0}])  # 겹친 두 구간을 합침
            self.assertEqual((body["status"], body["attempts"], body["duration_sec"]), ("queued", 1, 15.0))
            key, video, segments, subs, title = cs.call_args.args
            self.assertEqual(subs, [{"start_sec": 97.0, "end_sec": 99.0, "text": "케리아 들어갑니다"}])  # 고친 문장
            self.assertEqual(title, "T1 vs BLG · 킬 2")
            again = self.post({"event_ids": [1, 2]})
            self.assertEqual((again.status_code, again.json()["id"]), (200, body["id"]))
            self.assertEqual(cs.call_count, 1)  # 같은 요청은 다시 맡기지 않음

    def test_refresh_done_uploads(self, _src):
        with mock.patch("api.shorts.shorts.analyzer.create_short", side_effect=lambda key, *a: analyzer_state(key)):
            sid = self.post({"event_ids": [1]}).json()["id"]
        short = Short.objects.get(pk=sid)
        done = analyzer_state(short.key, "succeeded", output=f"t/shorts/{short.key}.mp4", render_sec=2.8)
        with mock.patch("api.shorts.shorts.analyzer.get_short", return_value=done), \
                mock.patch("api.shorts.shorts.storage.upload_file") as up:
            body = self.client.get(f"/shorts/{sid}").json()
        self.assertEqual((body["status"], body["render_sec"]), ("done", 2.8))
        self.assertTrue(body["video_url"].endswith(f"/shorts/{short.key}.mp4"))
        self.assertEqual(up.call_args.args[1], f"shorts/{short.key}.mp4")
        self.assertEqual(self.client.get(f"/games/{self.v.id}/shorts").json()["shorts"][0]["id"], sid)

    def test_analyzer_restart_resubmits_and_failed_retries(self, _src):
        with mock.patch("api.shorts.shorts.analyzer.create_short", side_effect=lambda key, *a: analyzer_state(key)) as cs:
            sid = self.post({"event_ids": [1]}).json()["id"]
            with mock.patch("api.shorts.shorts.analyzer.get_short", side_effect=ApiError("없음", 404)):
                body = self.client.get(f"/shorts/{sid}").json()  # analyzer 가 기록을 잃음 → 다시 맡김
            self.assertEqual((body["status"], body["attempts"], cs.call_count), ("queued", 2, 2))
            key = Short.objects.get(pk=sid).key
            with mock.patch("api.shorts.shorts.analyzer.get_short", return_value=analyzer_state(key, "failed", error="ffmpeg 실패")):
                self.assertEqual(self.client.get(f"/shorts/{sid}").json()["error"], "ffmpeg 실패")
            retry = self.post({"event_ids": [1]})  # 실패한 숏폼은 같은 요청으로 다시 렌더
            self.assertEqual((retry.status_code, retry.json()["attempts"], cs.call_count), (200, 3, 3))

    def test_analyzer_down_marks_failed(self, _src):
        with mock.patch("api.shorts.shorts.analyzer.create_short", side_effect=ApiError("analyzer 에 연결하지 못했습니다", 502)):
            res = self.post({"event_ids": [1]})
        self.assertEqual(res.status_code, 502)
        self.assertEqual(Short.objects.get().status, "failed")

    def test_bad_requests(self, _src):
        for body, msg in [({}, "event_ids"), ({"event_ids": [99]}, "없는 이벤트"), ({"event_ids": [1, 2, 3, 4, 5, 6]}, "5개"),
                          ({"event_ids": [1], "subtitles": "jp"}, "subtitles"), ({"event_ids": [1], "pre_sec": 30}, "pre_sec"),
                          ({"event_ids": [1], "subtitles": "en"}, "subtitles")]:
            res = self.post(body)
            self.assertEqual(res.status_code, 400, body)
            self.assertIn(msg, res.json()["error"])
        self.assertEqual(self.client.get("/shorts/999").status_code, 404)
