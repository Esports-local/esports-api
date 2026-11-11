"""스펙 시트 episodes 탭 (5번 호출)."""

from django.test import override_settings

from tests.base import DemoDataTestCase
from vod.models import Episode


class EpisodeTests(DemoDataTestCase):
    def test_detail(self):
        ep = Episode.objects.get(series=self.series, number=3)
        body = self.client.get(f"/episodes/{ep.id}").json()
        self.assertEqual(body["series_id"], self.series.id)
        self.assertIsNone(body["play_url"])  # 영상 없음
        self.assertEqual(body["duration"], 3600.0)

    def test_detail_not_found(self):
        r = self.client.get("/episodes/0")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"error": "회차를 찾을 수 없습니다"})

    @override_settings(S3_PUBLIC_ENDPOINT_URL="http://localhost:9000", S3_BUCKET="vod")
    def test_play_url_is_unsigned_public_hls(self):
        # master.m3u8 안의 index.m3u8·ts 는 상대 경로로 요청되므로 서명 없는 공개 주소여야 한다
        ep = Episode.objects.get(series=self.series, number=1)
        ep.hls_key = f"hls/{ep.id}/master.m3u8"
        ep.save()
        url = self.client.get(f"/episodes/{ep.id}").json()["play_url"]
        self.assertEqual(url, f"http://localhost:9000/vod/hls/{ep.id}/master.m3u8")
        self.assertNotIn("X-Amz", url)


class AnalysisTests(DemoDataTestCase):
    """6. GET /episodes/{id}/analysis"""

    def test_returns_main_original(self):
        ep = Episode.objects.get(series=self.series, number=1)
        body = self.client.get(f"/episodes/{ep.id}/analysis").json()
        self.assertEqual(body, ep.analysis)
        self.assertIn("start_sec", body["scenes"][0])  # 원본 그대로

    def test_not_analyzed(self):
        ep = Episode.objects.get(series=self.series, number=11)  # seed_demo: 11화는 분석 전
        r = self.client.get(f"/episodes/{ep.id}/analysis")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"error": "분석 결과가 없습니다"})


class LineReviewTests(DemoDataTestCase):
    """7·8. GET·POST /episodes/{id}/reviews"""

    def setUp(self):
        self.ep = Episode.objects.get(series=self.series, number=1)
        self.url = f"/episodes/{self.ep.id}/reviews"
        self.original = self.ep.analysis["scenes"][0]["lines"][0]["text"]

    def post(self, **body):
        return self.client.post(self.url, body, content_type="application/json")

    def test_empty_list(self):
        self.assertEqual(self.client.get(self.url).json(), {"episode_id": self.ep.id, "items": []})

    def test_save_overwrite_and_clear(self):
        r = self.post(scene_id=1, index=0, verdict="ok")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["review"]["verdict"], "ok")
        self.assertIsNone(r.json()["review"]["text"])

        r = self.post(scene_id=1, index=0, verdict="fixed", text="서류는 어디 있어요?")
        self.assertEqual(r.json()["review"]["text"], "서류는 어디 있어요?")
        items = self.client.get(self.url).json()["items"]
        self.assertEqual(len(items), 1)  # 덮어쓰기
        self.assertEqual(set(items[0]), {"scene_id", "index", "verdict", "text", "updated_at"})

        r = self.post(scene_id=1, index=0, verdict="clear")
        self.assertEqual(r.json(), {"review": None})
        self.assertEqual(self.client.get(self.url).json()["items"], [])

    def test_text_ignored_unless_fixed(self):
        r = self.post(scene_id=1, index=0, verdict="wrong", text="무시됨")
        self.assertIsNone(r.json()["review"]["text"])

    def test_fixed_needs_new_text(self):
        for text in (None, "", self.original):
            body = {"scene_id": 1, "index": 0, "verdict": "fixed"}
            if text is not None:
                body["text"] = text
            r = self.post(**body)
            self.assertEqual(r.status_code, 400, text)
            self.assertEqual(r.json(), {"error": "고친 대사를 입력해 주세요"})

    def test_line_not_found(self):
        for scene_id, index in ((1, 5), (99, 0), (2, 0)):  # 2번 장면은 대사 없음
            r = self.post(scene_id=scene_id, index=index, verdict="ok")
            self.assertEqual(r.status_code, 404, (scene_id, index))
            self.assertEqual(r.json(), {"error": "대사를 찾을 수 없습니다"})

    def test_invalid_verdict(self):
        r = self.post(scene_id=1, index=0, verdict="maybe")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "verdict 는 ok, wrong, fixed, clear 중 하나여야 합니다"})

    def test_not_analyzed(self):
        ep = Episode.objects.get(series=self.series, number=11)
        self.assertEqual(self.client.get(f"/episodes/{ep.id}/reviews").json(), {"error": "분석 결과가 없습니다"})
