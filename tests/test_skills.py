"""/skills 엔드포인트: 사용 기록, 선택 평가 결과, 평가 실행 요청."""

from datetime import datetime, timezone as tz
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from skills.models import SkillEvalCase, SkillEvalJob, SkillEvalRun, SkillFix, SkillImproveTry, SkillUsage

ADD = "esports-dev:add-endpoint"
STAGE = "esports-dev:add-stage"


def row(case_id, run, expect, got, verdict, skill=ADD, **extra):
    return {"id": case_id, "run": run, "skill": skill, "kind": "should" if expect == skill else "should_not",
            "split": "train", "repo": "esports-api", "prompt": f"{case_id} 요청", "expect": expect, "got": got,
            "first_tool": "Skill" if got else "Bash", "verdict": verdict, "model": "sonnet",
            "input_tokens": 30000, "sec": 3.5, "error": None, "at": "2026-11-17T10:00:00", **extra}


ROWS = [
    row("add-endpoint-s1", 1, ADD, ADD, "correct"),
    row("add-endpoint-s1", 2, ADD, ADD, "correct"),
    row("add-endpoint-s2", 1, ADD, None, "miss", first_input="grep -rn progress api/"),
    row("add-endpoint-s2", 2, ADD, None, "miss", first_input="ls api/games"),
    row("add-endpoint-n1", 1, None, None, "correct"),
    row("add-endpoint-n4", 1, STAGE, ADD, "wrong"),
]


class SkillEvalsTest(TestCase):
    def post(self, rows=ROWS, batch="base"):
        return self.client.post("/skills/evals", {"batch": batch, "rows": rows}, content_type="application/json")

    def test_save_and_summary(self):
        self.assertEqual(self.post().json(), {"saved": 6})
        d = self.client.get("/skills").json()
        self.assertEqual(d["batch"], "base")
        self.assertEqual(d["totals"]["eval_runs"], 6)
        self.assertEqual((d["totals"]["correct"], d["totals"]["miss"], d["totals"]["wrong"]), (3, 2, 1))
        by = {s["skill"]: s["eval"] for s in d["skills"]}
        # add-endpoint: 골라야 함 4, 고름 3, 맞음 2
        self.assertEqual((by[ADD]["should"], by[ADD]["picked"], by[ADD]["hit"]), (4, 3, 2))
        self.assertEqual((by[ADD]["precision"], by[ADD]["recall"]), (0.6667, 0.5))
        self.assertEqual((by[ADD]["miss"], by[ADD]["wrong"]), (2, 1))
        self.assertEqual(by[STAGE]["recall"], 0.0)  # 골라야 했는데 add-endpoint 를 고름

    def test_resend_does_not_duplicate(self):
        self.post()
        self.post([row("add-endpoint-s2", 1, ADD, ADD, "correct")])
        self.assertEqual(SkillEvalRun.objects.count(), 6)
        self.assertEqual(SkillEvalRun.objects.get(case_id="add-endpoint-s2", run=1).verdict, "correct")

    def test_failed_runs_are_skipped(self):
        r = self.post([row("add-endpoint-s3", 1, ADD, None, "miss", error="limit")])
        self.assertEqual(r.json(), {"saved": 0})

    def test_cases(self):
        self.post()
        cases = self.client.get("/skills/evals").json()["cases"]
        self.assertEqual([c["id"] for c in cases], ["add-endpoint-n4", "add-endpoint-s2"])  # 틀린 요청만
        s2 = cases[1]
        self.assertEqual((s2["runs"], s2["miss"], s2["did"]), (2, 2, [{"name": "(Bash)", "count": 2}]))
        self.assertEqual(s2["inputs"], ["grep -rn progress api/", "ls api/games"])  # 첫 Bash 명령
        self.assertEqual(len(self.client.get("/skills/evals?only=all").json()["cases"]), 4)
        self.assertEqual(len(self.client.get(f"/skills/evals?skill={STAGE}").json()["cases"]), 1)

    def test_compare(self):
        self.post(batch="base")
        self.post([row("add-endpoint-s2", 1, ADD, ADD, "correct", at="2026-11-18T10:00:00")], batch="after-1")
        d = self.client.get("/skills?batch=after-1&compare=base").json()
        add = next(s for s in d["skills"] if s["skill"] == ADD)
        self.assertEqual((d["compare"], add["eval"]["recall"], add["compare"]["recall"]), ("base", 1.0, 0.5))
        self.assertIsNone(self.client.get("/skills?batch=base&compare=base").json()["compare"])

    def test_latest_batch_is_default(self):
        self.post()
        self.post([row("add-endpoint-s1", 1, ADD, ADD, "correct", at="2026-11-17T12:00:00")], batch="after")
        d = self.client.get("/skills").json()
        self.assertEqual((d["batch"], d["totals"]["eval_runs"]), ("after", 1))
        self.assertEqual(self.client.get("/skills?batch=base").json()["totals"]["eval_runs"], 6)

    def test_errors(self):
        self.assertEqual(self.post(rows=[]).status_code, 400)
        r = self.post([row("x", 1, ADD, ADD, "nope")])
        self.assertEqual((r.status_code, "verdict" in r.json()["error"]), (400, True))
        self.assertEqual(self.client.get("/skills/evals?only=x").status_code, 400)
        self.assertEqual(self.client.get("/skills?days=0").status_code, 400)


class SkillUsageTest(TestCase):
    def post(self, records):
        return self.client.post("/skills/usage", {"records": records}, content_type="application/json")

    def test_usage_summary(self):
        recs = [
            {"id": "a", "skill": ADD, "repo": "esports-api", "ok": True, "duration_sec": 10.0, "input_tokens": 1000,
             "output_tokens": 200, "tool_calls": 5, "tool_errors": 0, "used_at": "2026-11-17T10:00:00+09:00"},
            {"id": "b", "skill": ADD, "repo": "esports-ui", "ok": False, "duration_sec": 30.0, "input_tokens": 3000,
             "output_tokens": 400, "tool_calls": 8, "tool_errors": 2, "used_at": "2026-11-17T11:00:00+09:00"},
            {"id": "c", "skill": ADD, "used_at": "2026-11-17T12:00:00+09:00"},  # 아직 안 끝난 호출
        ]
        self.assertEqual(self.post(recs).status_code, 201)
        with mock.patch.object(timezone, "now", return_value=datetime(2026, 11, 18, tzinfo=tz.utc)):
            u = self.client.get("/skills").json()["skills"][0]["usage"]
        self.assertEqual((u["calls"], u["success_rate"], u["avg_sec"]), (3, 0.5, 20.0))
        self.assertEqual((u["input_tokens"], u["output_tokens"], u["tool_errors"]), (4000, 600, 2))

    def test_resend_updates_same_record(self):
        self.post([{"id": "a", "skill": ADD, "used_at": "2026-11-17T10:00:00+09:00"}])
        self.post([{"id": "a", "skill": ADD, "ok": True, "duration_sec": 4, "used_at": "2026-11-17T10:00:00+09:00"}])
        self.assertEqual(SkillUsage.objects.count(), 1)
        self.assertTrue(SkillUsage.objects.get().ok)

    def test_errors(self):
        self.assertEqual(self.post([{"skill": ADD, "used_at": "2026-11-17T10:00:00"}]).status_code, 400)
        r = self.post([{"id": "a", "skill": ADD, "used_at": "어제"}])
        self.assertEqual((r.status_code, r.json()["error"]), (400, "used_at 은 ISO8601 시각이어야 합니다"))


class SkillEvalJobsTest(TestCase):
    def create(self, **body):
        return self.client.post("/skills/evals/jobs", {"batch": "base", **body}, content_type="application/json")

    def test_job_flow(self):
        job = self.create(skills=["esports-dev:add-stage"], repeat=2).json()
        self.assertEqual((job["status"], job["skills"], job["repeat"], job["model"]),
                         ("queued", ["add-stage"], 2, "sonnet"))
        self.assertEqual(self.create().status_code, 409)  # 한 번에 하나
        self.assertEqual(self.client.get("/skills").json()["job"]["id"], job["id"])

        self.assertIsNone(self.client.post("/skills/evals/jobs/claim").json()["job"])  # 화면에서 허용 전에는 안 줌
        self.client.post("/skills/evals/runner", {"enabled": True}, content_type="application/json")
        claimed = self.client.post("/skills/evals/jobs/claim").json()["job"]
        self.assertEqual((claimed["id"], claimed["status"]), (job["id"], "running"))
        self.assertIsNone(self.client.post("/skills/evals/jobs/claim").json()["job"])

        url = f"/skills/evals/jobs/{job['id']}/progress"
        p = self.client.post(url, {"total": 12, "done": 5}, content_type="application/json").json()
        self.assertEqual((p["total"], p["done"], p["status"]), (12, 5, "running"))
        p = self.client.post(url, {"done": 12, "status": "done"}, content_type="application/json").json()
        self.assertEqual((p["status"], p["finished_at"] is not None), ("done", True))
        self.assertIsNone(self.client.get("/skills").json()["job"])
        self.assertEqual(self.create().status_code, 201)  # 끝났으니 다시 요청할 수 있다

    def test_runner(self):
        r = self.client.get("/skills/evals/runner").json()
        self.assertEqual((r["enabled"], r["online"]), (False, False))
        self.client.post("/skills/evals/jobs/claim")  # 실행기가 물어보면 연결된 것으로 보인다
        self.assertTrue(self.client.get("/skills").json()["runner"]["online"])
        self.assertTrue(self.client.post("/skills/evals/runner", {"enabled": True},
                                         content_type="application/json").json()["enabled"])
        self.assertEqual(self.client.post("/skills/evals/runner", {"enabled": "yes"},
                                          content_type="application/json").status_code, 400)

    def test_job_with_case_ids(self):
        job = self.create(case_ids=["add-endpoint-s2", "docs-sync-s3"]).json()
        self.assertEqual(job["case_ids"], ["add-endpoint-s2", "docs-sync-s3"])
        SkillEvalJob.objects.all().delete()
        self.assertEqual(self.create(case_ids="add-endpoint-s2").status_code, 400)

    def test_cancel_stops_progress(self):
        job = self.create().json()
        self.client.post("/skills/evals/jobs/claim")
        self.assertEqual(self.client.post(f"/skills/evals/jobs/{job['id']}/cancel").json()["status"], "cancelled")
        p = self.client.post(f"/skills/evals/jobs/{job['id']}/progress", {"done": 3}, content_type="application/json")
        self.assertEqual((p.json()["status"], p.json()["done"]), ("cancelled", 0))  # 실행기가 이걸 보고 멈춘다

    def test_errors(self):
        self.assertEqual(self.create(model="fable").status_code, 400)
        self.assertEqual(self.create(repeat=9).status_code, 400)
        self.assertEqual(self.create(batch="../x").status_code, 400)
        self.assertEqual(self.client.post("/skills/evals/jobs/999/cancel").json(), {"error": "평가 실행을 찾을 수 없습니다"})
        self.assertEqual(SkillEvalJob.objects.count(), 0)


class SkillEvalCasesTest(TestCase):
    FILE = [{"id": "add-endpoint-s1", "skill": ADD, "kind": "should", "split": "train", "repo": "esports-api",
             "prompt": "엔드포인트 만들어 줘", "expect": ADD},
            {"id": "add-endpoint-n1", "skill": ADD, "kind": "should_not", "split": "val", "repo": "esports-ui",
             "prompt": "탭 색 바꿔 줘", "expect": None}]

    def add(self, **body):
        base = {"skill": ADD, "kind": "should", "split": "train", "repo": "esports-api", "prompt": "필드 하나 추가해 줘"}
        return self.client.post("/skills/cases", {**base, **body}, content_type="application/json")

    def sync(self, cases):
        return self.client.post("/skills/cases/sync", {"cases": cases}, content_type="application/json").json()

    def test_add_then_worker_moves_it_to_file(self):
        self.assertEqual(self.sync(self.FILE), {"saved": 2, "pending": [], "changes": []})
        c = self.add().json()
        self.assertEqual((c["id"], c["expect"], c["origin"], c["synced"]), ("add-endpoint-u1", ADD, "ui", False))
        self.assertEqual(self.add(prompt="다른 문장", kind="should_not", expect=STAGE).json()["id"], "add-endpoint-u2")

        pending = self.sync(self.FILE)["pending"]  # 실행기가 받아서 파일에 옮겨 적는다
        self.assertEqual([p["id"] for p in pending], ["add-endpoint-u1", "add-endpoint-u2"])
        self.assertEqual(self.sync(self.FILE + pending)["pending"], [])
        self.assertTrue(SkillEvalCase.objects.get(case_id="add-endpoint-u1").synced)
        self.assertEqual(len(self.client.get(f"/skills/cases?skill={ADD}").json()["cases"]), 4)
        self.assertEqual(len(self.client.get("/skills/cases?origin=ui").json()["cases"]), 2)

    def test_removed_from_file_is_removed(self):
        self.sync(self.FILE)
        self.add()
        self.sync(self.FILE[:1])
        self.assertEqual(sorted(SkillEvalCase.objects.values_list("case_id", flat=True)),
                         ["add-endpoint-s1", "add-endpoint-u1"])  # 아직 안 옮긴 화면 추가분은 남는다

    def edit(self, case_id, **body):
        return self.client.post(f"/skills/cases/{case_id}", body, content_type="application/json")

    def post_runs(self, rows):
        return self.client.post("/skills/evals", {"batch": "base", "rows": rows}, content_type="application/json")

    def test_edit_expect_rejudges_runs(self):
        self.sync(self.FILE)
        self.post_runs([row("add-endpoint-s1", 1, ADD, None, "miss"), row("add-endpoint-s1", 2, ADD, ADD, "correct")])
        c = self.edit("add-endpoint-s1", expect="").json()  # 스킬 없이 답해도 되는 요청이었다
        self.assertEqual((c["expect"], c["kind"], c["change"]), (None, "should_not", "edit"))
        verdicts = list(SkillEvalRun.objects.order_by("run").values_list("verdict", flat=True))
        self.assertEqual(verdicts, ["correct", "wrong"])
        self.assertEqual(self.client.get("/skills").json()["totals"]["miss"], 0)

        # 옛 정답이 든 결과 파일을 다시 보내도 지금 정답으로 판정한다
        self.post_runs([row("add-endpoint-s1", 1, ADD, None, "miss")])
        self.assertEqual(SkillEvalRun.objects.get(run=1).verdict, "correct")

        # 실행기가 파일을 고치기 전에는 파일의 옛 값으로 덮지 않는다
        d = self.sync(self.FILE)
        self.assertEqual([x["id"] for x in d["changes"]], ["add-endpoint-s1"])
        self.assertEqual(SkillEvalCase.objects.get(case_id="add-endpoint-s1").expect, "")
        fixed = [{**self.FILE[0], "kind": "should_not", "expect": None}, self.FILE[1]]
        self.assertEqual(self.client.post("/skills/cases/sync", {"cases": fixed, "applied": ["add-endpoint-s1"]},
                                          content_type="application/json").json()["changes"], [])
        self.assertEqual(SkillEvalCase.objects.get(case_id="add-endpoint-s1").change, "")

    def test_file_answer_change_rejudges_runs(self):
        self.sync([self.FILE[0], {**self.FILE[1], "expect": STAGE}])  # 그때 파일 정답은 add-stage
        self.post_runs([row("add-endpoint-n1", 1, STAGE, None, "miss")])
        self.assertEqual(SkillEvalRun.objects.get().verdict, "miss")
        self.sync(self.FILE)  # 파일에서 정답을 스킬 없음으로 바꿈 (스킬을 뺐을 때처럼)
        self.assertEqual(SkillEvalRun.objects.get().verdict, "correct")

    def test_remove(self):
        self.sync(self.FILE)
        self.post_runs([row("add-endpoint-n1", 1, None, None, "correct")])
        self.assertEqual(self.edit("add-endpoint-n1", remove=True).json(), {"id": "add-endpoint-n1", "removed": True})
        self.assertFalse(SkillEvalRun.objects.exists())
        self.post_runs([row("add-endpoint-n1", 1, None, None, "correct")])  # 다시 보내도 안 들어간다
        self.assertFalse(SkillEvalRun.objects.exists())
        self.assertEqual([x["change"] for x in self.sync(self.FILE)["changes"]], ["remove"])
        self.client.post("/skills/cases/sync", {"cases": self.FILE[:1], "applied": ["add-endpoint-n1"]},
                         content_type="application/json")
        self.assertFalse(SkillEvalCase.objects.filter(case_id="add-endpoint-n1").exists())

        u = self.add().json()["id"]  # 아직 파일에 없는 화면 추가분은 바로 지운다
        self.edit(u, remove=True)
        self.assertFalse(SkillEvalCase.objects.filter(case_id=u).exists())

    def test_edit_errors(self):
        self.sync(self.FILE)
        self.assertEqual(self.edit("nope", expect="").status_code, 404)
        self.assertEqual(self.edit("add-endpoint-s1").status_code, 400)
        self.assertEqual(self.edit("add-endpoint-s1", expect="graphify").status_code, 400)

    def test_errors(self):
        self.assertEqual(self.add(prompt=" ").json(), {"error": "prompt 가 필요합니다"})
        self.assertEqual(self.add(repo="other").status_code, 400)
        self.assertEqual(self.add(kind="should_not", expect=ADD).status_code, 400)
        self.add()
        self.assertEqual(self.add().status_code, 409)  # 같은 문장


class SkillImproveTriesTest(TestCase):
    ENTRY = {"try": 1, "at": "2026-11-17T15:06:54", "skill": ADD, "model": "sonnet", "cause": "범위",
             "hypothesis": "가설", "change": "변경", "before_description": "전", "description": "후",
             "accepted": False, "reason": "개선용이 안 오름", "train_before": 0.625, "train_quick": 0.5,
             "ledger": [{"prompt": "a", "status": "broken"}, {"prompt": "b", "status": "same"}]}

    def post(self, tries):
        return self.client.post("/skills/improves", {"tries": tries}, content_type="application/json")

    def test_save_and_list(self):
        self.assertEqual(self.post([self.ENTRY]).json(), {"saved": 1})
        self.post([{**self.ENTRY, "invalid": "환경이 달랐음"}])  # 다시 보내면 덮어쓴다
        t = self.client.get(f"/skills/improves?skill={ADD}").json()["tries"]
        self.assertEqual(len(t), 1)
        self.assertEqual((t[0]["cause"], t[0]["invalid"], t[0]["broken"], t[0]["scores"]),
                         ("범위", "환경이 달랐음", ["a"], {"train_before": 0.625, "train_quick": 0.5}))
        self.assertEqual(self.post([{"try": 1}]).status_code, 400)
        self.post([{**self.ENTRY, "try": 2, "proposed": True}])
        self.assertTrue(self.client.get("/skills/improves").json()["tries"][0]["proposed"])  # 최신 시도가 먼저
        self.assertEqual(SkillImproveTry.objects.count(), 2)


class SkillFixesTest(TestCase):
    FIX = {"case_id": "local-up-s3", "skill": "esports-dev:local-up", "repo": "esports-analyzer",
           "advice": "claudemd", "routing": {"has_line": False, "others": ["esports-api"], "line": "- 로컬 → `esports-dev:local-up`"}}

    def post(self, fixes):
        return self.client.post("/skills/fixes", {"fixes": fixes}, content_type="application/json")

    def test_replace_and_list(self):
        self.assertEqual(self.post([self.FIX]).json(), {"saved": 1})
        f = self.client.get("/skills/fixes").json()["fixes"][0]
        self.assertEqual((f["case_id"], f["advice"], f["routing"]["has_line"]), ("local-up-s3", "claudemd", False))
        self.post([])  # 더 이상 안 틀리면 지운다
        self.assertFalse(SkillFix.objects.exists())
        self.assertEqual(self.post([{"case_id": "x"}]).status_code, 400)

    def test_fix_jobs(self):
        job = lambda **b: self.client.post("/skills/evals/jobs", b, content_type="application/json")
        r = job(kind="apply_line", params={"repo": "esports-analyzer", "skill": "local-up", "line": "- x"}, case_ids=["local-up-s3"])
        self.assertEqual((r.status_code, r.json()["kind"], r.json()["batch"]), (201, "apply_line", "recheck"))
        SkillEvalJob.objects.all().delete()
        self.assertEqual(job(kind="propose", params={}).status_code, 400)  # skill 이 없음
        self.assertEqual(job(kind="apply_line", params={"repo": "x", "skill": "a", "line": "b"}).status_code, 400)
        self.assertEqual(job(kind="nope").status_code, 400)
        self.assertEqual(job(kind="propose", params={"skill": "local-up"}).json()["batch"], "propose")
