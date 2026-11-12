"""대사 검수 POST /games/{id}/lines/{line_id}/review (스펙 시트 13번)와 번역 연동."""

from unittest import mock

from django.test import TestCase

from matches.models import GameVideo, LineReview

LINES = [
    {"id": 1, "start_sec": 10.0, "end_sec": 12.0, "speaker": None, "language": "ko", "text": "캐리아 좋아요"},
    {"id": 2, "start_sec": 50.0, "end_sec": 52.0, "speaker": None, "language": "ko", "text": "티언 승리"},
]


def asr(lines):
    return {"asr": {"schema_version": 1, "stage": "asr", "params": {}, "result": {"lines": lines}}}


class LineReviewTest(TestCase):
    def setUp(self):
        self.v = GameVideo.objects.create(title="t", work_name="game_1080", video_name="game_1080.mp4",
                                          analyze_status="done", results=asr(LINES))

    def post(self, line_id, body):
        return self.client.post(f"/games/{self.v.id}/lines/{line_id}/review", body, content_type="application/json")

    def lines(self):
        return {x["id"]: x for x in self.client.get(f"/games/{self.v.id}/lines").json()}

    def test_edit_and_mark(self):
        self.assertIsNone(self.lines()[1]["review"])
        r = self.post(1, {"text": " 케리아 좋아요 ", "reviewed": True}).json()
        self.assertEqual(r["review"]["text"], "케리아 좋아요")
        self.assertTrue(r["review"]["reviewed"])
        line = self.lines()[1]
        self.assertEqual(line["text"], "캐리아 좋아요")  # 원문은 그대로
        self.assertEqual(line["review"]["text"], "케리아 좋아요")
        # 표시만 바꾸면 고친 문장은 남는다
        self.assertFalse(self.post(1, {"reviewed": False}).json()["review"]["reviewed"])
        self.assertEqual(self.lines()[1]["review"]["text"], "케리아 좋아요")
        # 원문과 같은 문장을 보내면 안 고친 것으로
        self.assertIsNone(self.post(1, {"text": "캐리아 좋아요"}).json()["review"]["text"])

    def test_errors(self):
        self.assertEqual(self.post(1, {}).status_code, 400)
        self.assertEqual(self.post(1, {"text": "  "}).status_code, 400)
        self.assertEqual(self.post(1, {"reviewed": "yes"}).status_code, 400)
        self.assertEqual(self.post(99, {"reviewed": True}).status_code, 404)
        self.assertEqual(self.client.post(f"/games/{self.v.id + 1}/lines/1/review", {"reviewed": True},
                                          content_type="application/json").status_code, 404)

    def test_asr_rerun_drops_stale_review(self):
        self.post(2, {"text": "티원 승리", "reviewed": True})
        self.v.results = asr([LINES[0], {**LINES[1], "text": "티원이 승리"}])
        self.v.save()
        self.assertIsNone(self.lines()[2]["review"])  # 원문이 바뀌어 쓰지 않음
        r = self.post(2, {"reviewed": True}).json()["review"]  # 다시 검수하면 새로 시작
        self.assertIsNone(r["text"])
        self.assertEqual(LineReview.objects.get(video=self.v, line_id=2).asr_text, "티원이 승리")

    def test_translate_and_estimate_use_fixed_text(self):
        self.post(2, {"text": "티원 승리"})
        self.post(1, {"reviewed": True})  # 안 고친 대사는 넘기지 않는다
        with mock.patch("api.games.analyzer.list_videos", return_value=[{"name": "game_1080.mp4", "selectable": True}]), \
             mock.patch("api.games.analyzer.start_job", return_value={"status": "running"}) as start, \
             mock.patch("api.games.analyzer.get_job", return_value={"status": "running"}):
            r = self.client.post(f"/games/{self.v.id}/analyze", {"stages": ["translate"], "conditions": ["A"]},
                                 content_type="application/json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(start.call_args.args[3],
                         {"translate": {"conditions": ["A"], "text_overrides": {"2": "티원 승리"}}})
        with mock.patch("api.games.analyzer.estimate", return_value={}) as est:
            self.client.get(f"/games/{self.v.id}/estimate?conditions=A")
        est.assert_called_once_with("game_1080.mp4", ["A"], {"2": "티원 승리"})
