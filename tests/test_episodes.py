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
