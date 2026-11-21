"""대사 검수 POST /games/{id}/lines/{line_id}/review (스펙 시트 13번)와 고친 문장(숏폼 자막)."""

from django.test import TestCase

from api.games import reviews
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

    def test_text_overrides_only_fixed(self):
        self.post(2, {"text": "티원 승리"})
        self.post(1, {"reviewed": True})  # 안 고친 대사는 빠진다
        self.assertEqual(reviews.text_overrides(self.v), {"2": "티원 승리"})
