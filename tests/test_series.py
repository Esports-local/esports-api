"""스펙 시트 series 탭 (1~4번 호출)."""

from tests.base import DemoDataTestCase


class SeriesTests(DemoDataTestCase):
    def test_list(self):
        r = self.client.get("/series")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()[0]), {"id", "title", "poster", "episode_count", "first_air_date"})

    def test_detail(self):
        r = self.client.get(f"/series/{self.series.id}")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(body["episodes"]), 12)
        self.assertEqual(set(body["episodes"][0]),
                         {"id", "number", "title", "air_date", "has_video", "analyze_status"})
        self.assertEqual(body["characters"][0]["aliases"], ["김 대리"])

    def test_detail_not_found(self):
        r = self.client.get("/series/0")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {"error": "작품을 찾을 수 없습니다"})


class PredictTests(DemoDataTestCase):
    def url(self):
        return f"/series/{self.series.id}/predict"

    def test_idle_then_done(self):
        self.assertEqual(self.client.get(self.url(), {"target": 11}).json()["status"], "idle")
        r = self.client.post(self.url(), {"target": 11}, content_type="application/json")
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json(), {"target": 11, "status": "queued"})
        body = self.client.get(self.url(), {"target": 11}).json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["used_episodes"], list(range(1, 11)))
        ev = body["items"][0]["evidence"][0]
        self.assertEqual(set(ev), {"episode_id", "scene_id", "start", "end", "note"})

    def test_errors(self):
        # 11화는 분석 안 됨 → target 12 불가
        r = self.client.post(self.url(), {"target": 12}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"error": "11화 분석이 완료되지 않았습니다"})
        r = self.client.post(self.url(), {}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("target", r.json()["error"])
        self.assertEqual(self.client.get(self.url()).json(), {"error": "target 이 필요합니다"})
