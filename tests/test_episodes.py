"""스펙 시트 episodes 탭 (5번 호출)."""

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
