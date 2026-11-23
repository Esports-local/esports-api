"""장면 전환 검수 (스펙 19·20번)."""

from django.test import TestCase

from matches.models import CutReview, GameVideo

SEGMENTS = {"stage": "segments", "result": {"transitions": [
    {"id": 1, "start_sec": 10.0, "end_sec": 10.0, "kind": "cut"},
    {"id": 2, "start_sec": 20.0, "end_sec": 21.0, "kind": "dissolve"},
    {"id": 3, "start_sec": 30.0, "end_sec": 32.0, "kind": "wipe"}]}}


class CutReviewTest(TestCase):
    def setUp(self):
        self.v = GameVideo.objects.create(title="t", work_name="t", results={"segments": SEGMENTS})

    def post(self, tid, body):
        return self.client.post(f"/games/{self.v.id}/cuts/{tid}/review", body, content_type="application/json")

    def test_save_list_and_clear(self):
        r = self.post(1, {"verdict": "pass"})
        self.assertEqual((r.status_code, r.json()["summary"]), (200, {"total": 3, "pass": 1, "fail": 0, "unchecked": 2}))
        self.post(2, {"verdict": "fail"})
        self.post(1, {"verdict": "fail"})  # 덮어쓰기
        body = self.client.get(f"/games/{self.v.id}/cuts/reviews").json()
        self.assertEqual(sorted((x["transition_id"], x["verdict"]) for x in body["reviews"]), [(1, "fail"), (2, "fail")])
        self.assertEqual(self.post(2, {"verdict": None}).json()["summary"]["fail"], 1)  # 지움
        self.assertEqual(CutReview.objects.count(), 1)

    def test_stale_after_resegment(self):
        self.post(3, {"verdict": "pass"})
        seg = {"stage": "segments", "result": {"transitions": [{"id": 3, "start_sec": 31.0, "end_sec": 32.0, "kind": "wipe"}]}}
        GameVideo.objects.filter(pk=self.v.pk).update(results={"segments": seg})
        body = self.client.get(f"/games/{self.v.id}/cuts/reviews").json()
        self.assertEqual((body["reviews"], body["summary"]["unchecked"]), ([], 1))  # 시각이 바뀐 전환은 다시 검수

    def test_bad_requests(self):
        self.assertEqual(self.post(9, {"verdict": "pass"}).status_code, 404)
        self.assertEqual(self.post(1, {}).status_code, 400)
        self.assertEqual(self.post(1, {"verdict": "ok"}).status_code, 400)
