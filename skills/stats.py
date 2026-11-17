"""스킬별 집계: 사용 기록(호출 수·성공률·시간·토큰)과 선택 평가(정밀도·재현율)."""

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Max
from django.utils import timezone

from skills.models import SkillEvalCase, SkillEvalRun, SkillUsage

PLUGIN = "esports-dev:"


def judge(expect: str, got: str) -> str:
    """실행 한 번을 판정한다 (dev-workflow evals/run.py 의 judge 와 같은 규칙). 빈칸은 스킬 없음.

    esports-dev 스킬만 센다. 기대와 같으면 correct, 아무것도 안 골랐으면 miss, 다른 스킬이면 wrong.
    """
    ours = got if got.startswith(PLUGIN) else ""
    if ours == expect:
        return "correct"
    return "miss" if not ours else "wrong"


def batches() -> list[dict]:
    """평가 묶음 목록. 최근에 돌린 것이 먼저."""
    rows = (SkillEvalRun.objects.values("batch").annotate(runs=Count("id"), last_ran_at=Max("ran_at"))
            .order_by("-last_ran_at"))
    return [{"batch": r["batch"], "runs": r["runs"], "last_ran_at": r["last_ran_at"].isoformat()} for r in rows]


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def usage_by_skill(days: int) -> dict[str, dict]:
    """최근 days 일의 사용 기록을 스킬별로 모은다."""
    since = timezone.now() - timedelta(days=days)
    by = defaultdict(list)
    for u in SkillUsage.objects.filter(used_at__gte=since):
        by[u.skill].append(u)
    out = {}
    for skill, rows in by.items():
        known = [u for u in rows if u.ok is not None]
        secs = [u.duration_sec for u in rows if u.duration_sec is not None]
        out[skill] = {
            "calls": len(rows),
            "success_rate": _ratio(sum(1 for u in known if u.ok), len(known)),
            "avg_sec": round(sum(secs) / len(secs), 1) if secs else None,
            "input_tokens": sum(u.input_tokens or 0 for u in rows),
            "output_tokens": sum(u.output_tokens or 0 for u in rows),
            "tool_errors": sum(u.tool_errors or 0 for u in rows),
            "last_used_at": max(u.used_at for u in rows).isoformat(),
        }
    return out


def eval_by_skill(runs: list[SkillEvalRun]) -> dict[str, dict]:
    """평가 실행을 스킬별 정밀도·재현율로 모은다.

    should: 그 스킬을 골라야 했던 실행 수 · picked: 그 스킬을 고른 실행 수 · hit: 둘 다인 실행 수.
    """
    names = {r.skill for r in runs} | {r.expect for r in runs if r.expect}
    out = {}
    for skill in names:
        should = [r for r in runs if r.expect == skill]
        picked = [r for r in runs if r.got == skill]
        hit = sum(1 for r in should if r.got == skill)
        out[skill] = {
            "runs": sum(1 for r in runs if r.skill == skill),
            "should": len(should), "picked": len(picked), "hit": hit,
            "precision": _ratio(hit, len(picked)), "recall": _ratio(hit, len(should)),
            "miss": len(should) - hit,       # 써야 하는데 안 고름 (다른 스킬을 고른 경우 포함)
            "wrong": len(picked) - hit,      # 고르면 안 되는데 고름
        }
    return out


def summary(batch: str | None, days: int = 30, compare: str | None = None) -> dict:
    """GET /skills 응답. compare 를 주면 스킬마다 그 결과 이름의 평가도 붙인다 (전후 비교)."""
    all_batches = batches()
    if not batch and all_batches:
        batch = all_batches[0]["batch"]
    runs = list(SkillEvalRun.objects.filter(batch=batch)) if batch else []
    usage, evals = usage_by_skill(days), eval_by_skill(runs)
    verdicts = Counter(r.verdict for r in runs)
    other = eval_by_skill(list(SkillEvalRun.objects.filter(batch=compare))) if compare and compare != batch else {}
    skills = [{"skill": name, "usage": usage.get(name), "eval": evals.get(name), "compare": other.get(name)}
              for name in sorted(set(usage) | set(evals))]
    return {
        "batch": batch, "batches": all_batches, "days": days, "compare": compare if other else None,
        "totals": {"eval_runs": len(runs), "correct": verdicts["correct"], "miss": verdicts["miss"],
                   "wrong": verdicts["wrong"], "accuracy": _ratio(verdicts["correct"], len(runs)),
                   "models": sorted({r.model for r in runs}),
                   "usage_calls": sum(u["calls"] for u in usage.values())},
        "skills": skills,
    }


def cases(batch: str | None, skill: str | None, only: str) -> list[dict]:
    """평가 요청별 결과. only: failed(틀린 적 있는 요청) | miss | wrong | all."""
    if not batch:
        latest = batches()
        batch = latest[0]["batch"] if latest else None
    by = defaultdict(list)
    for r in SkillEvalRun.objects.filter(batch=batch):
        by[r.case_id].append(r)
    changes = dict(SkillEvalCase.objects.exclude(change="").values_list("case_id", "change"))
    out = []
    for case_id, runs in by.items():
        first = runs[0]
        if skill and skill not in {first.skill, first.expect} | {r.got for r in runs}:
            continue
        count = Counter(r.verdict for r in runs)
        if only == "failed" and not (count["miss"] or count["wrong"]):
            continue
        if only in ("miss", "wrong") and not count[only]:
            continue
        did = Counter((r.got or f"({r.first_tool or '도구 없이 답함'})") for r in runs if r.verdict != "correct")
        out.append({"id": case_id, "skill": first.skill, "kind": first.kind, "split": first.split,
                    "repo": first.repo, "prompt": first.prompt, "expect": first.expect or None,
                    "runs": len(runs), "correct": count["correct"], "miss": count["miss"], "wrong": count["wrong"],
                    "did": [{"name": k, "count": v} for k, v in did.most_common()],
                    "inputs": sorted({r.first_input for r in runs if r.verdict != "correct" and r.first_input})[:3],
                    "change": changes.get(case_id) or None})
    out.sort(key=lambda c: (-(c["miss"] + c["wrong"]) / c["runs"], c["id"]))
    return out
