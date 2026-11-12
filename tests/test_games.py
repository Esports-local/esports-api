"""세트 영상 /games 엔드포인트 (스펙 시트 spec_sheet_lol 1~5번)."""

from django.test import TestCase

from matches.models import GameVideo

RUNS = [
    {"tag": "team", "slot": "blue", "kind": "team", "text": "T1", "raw": "T1", "start_sec": 0, "end_sec": 100, "conf": 0.9, "samples": 200},
    {"tag": "player_name", "slot": "red_support", "kind": "player", "text": "ON", "raw": "ON", "start_sec": 0, "end_sec": 90, "conf": 0.9, "samples": 180},
    {"tag": "player_name", "slot": "red_support", "kind": "player", "text": "JON", "raw": "JON", "start_sec": 90, "end_sec": 91, "conf": 0.6, "samples": 2},
    {"tag": "team_kills", "slot": "red", "kind": "score", "text": "3", "raw": "3", "start_sec": 40, "end_sec": 60, "conf": 1.0, "samples": 40},
    {"tag": "kda", "slot": "blue_top", "kind": "score", "text": "10/0/0", "raw": "10/0/0", "start_sec": 45, "end_sec": 45.5, "conf": 0.5, "samples": 1},
]
LINES = [
    {"id": 1, "start_sec": 10.0, "end_sec": 12.0, "speaker": None, "language": "ko", "text": "온 선수"},
    {"id": 2, "start_sec": 50.0, "end_sec": 52.0, "speaker": None, "language": "ko", "text": "캐리아"},
]


def stage(name, result):
    return {"schema_version": 1, "stage": name, "episode": "t", "params": {}, "result": result}


class GamesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.v = GameVideo.objects.create(
            title="테스트 세트", work_name="t", duration=100.0, analyze_status="done",
            run_log=[{"stage": "asr", "elapsed_sec": 5.0}],
            results={"roi_ocr": stage("roi_ocr", {"layout": "x.json", "sample_fps": 2.0, "runs": RUNS}),
                     "asr": stage("asr", {"lines": LINES}),
                     "translate": stage("translate", {"lines": {"2": {"A": "Karia", "B": "Keria", "C": "Keria"}}})})

    def test_list_and_detail(self):
        self.assertEqual(self.client.get("/games").json()[0]["title"], "테스트 세트")
        d = self.client.get(f"/games/{self.v.id}").json()
        self.assertIsNone(d["match"])
        status = {s["stage"]: (s["status"], s["elapsed_sec"]) for s in d["stages"]}
        self.assertEqual(status["asr"], ("done", 5.0))
        self.assertEqual(status["roi_ocr"], ("done", None))
        self.assertEqual(status["evaluate"], ("pending", None))

    def test_screen_filters_noise(self):
        runs = self.client.get(f"/games/{self.v.id}/screen?tag=kda,player_name").json()["runs"]
        self.assertEqual([r["text"] for r in runs], ["ON", "JON"])  # 1장짜리 10/0/0 은 빠짐
        self.assertEqual(self.client.get(f"/games/{self.v.id}/screen?min_samples=x").status_code, 400)

    def test_lines_with_screen_and_translations(self):
        lines = self.client.get(f"/games/{self.v.id}/lines").json()
        self.assertEqual(lines[0]["screen"]["player_name"]["red_support"], "ON")  # 가장 오래 뜬 이름
        self.assertNotIn("team_kills", lines[0]["screen"])
        self.assertEqual(lines[1]["screen"]["team_kills"], {"red": "3"})
        self.assertIsNone(lines[0]["translations"])
        self.assertEqual(lines[1]["translations"]["B"], "Keria")
        self.assertEqual(len(self.client.get(f"/games/{self.v.id}/lines?from_sec=20").json()), 1)

    def test_analysis_and_errors(self):
        self.assertEqual(self.client.get(f"/games/{self.v.id}/analysis?stage=asr").json()["stage"], "asr")
        self.assertEqual(self.client.get(f"/games/{self.v.id}/analysis?stage=nope").status_code, 400)
        r = self.client.get(f"/games/{self.v.id}/analysis?stage=evaluate")
        self.assertEqual((r.status_code, r.json()), (404, {"error": "evaluate 결과가 없습니다"}))
        self.assertEqual(self.client.get("/games/999").json(), {"error": "영상을 찾을 수 없습니다"})
