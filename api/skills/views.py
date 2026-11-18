"""/skills 엔드포인트: 스킬 사용 기록, 선택 평가 결과, 화면에서 요청하는 평가 실행.

기록을 보내는 쪽은 dev-workflow 레포다 (사용 기록 = 훅, 평가 결과 = evals/run.py, 평가 실행 = evals/worker.py).
"""

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.exceptions import ApiError, get_or_404
from skills import stats
from skills.models import ACTIVE, EvalRunner, JobStatus, SkillEvalCase, SkillEvalJob, SkillEvalRun, SkillImproveTry, SkillUsage, Verdict

MODELS = ["sonnet", "haiku"]  # 평가에 쓸 수 있는 모델 (기본 모델로 돌지 않게 고정)
MAX_REPEAT = 5
MAX_CASES = 500
JOB_NOT_FOUND = "평가 실행을 찾을 수 없습니다"
REPOS = ["esports-analyzer", "esports-api", "esports-ui"]  # 테스트 요청을 실행하는 폴더
CASE_FIELDS = ("skill", "kind", "split", "repo", "prompt")


def _time(value, name: str):
    t = parse_datetime(value) if isinstance(value, str) else None
    if t is None:
        raise ApiError(f"{name} 은 ISO8601 시각이어야 합니다")
    return timezone.make_aware(t) if timezone.is_naive(t) else t


def _list(data, key: str) -> list:
    items = data.get(key)
    if not isinstance(items, list) or not items:
        raise ApiError(f"{key} 는 비어 있지 않은 목록이어야 합니다")
    return items


def _number(value, cast=int):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = cast(value)
    except (TypeError, ValueError) as e:
        raise ApiError("숫자 항목에 숫자가 아닌 값이 있습니다") from e
    return n if n >= 0 else None


RUNNER_ONLINE_SEC = 30  # 실행기는 5초마다 물어본다. 이만큼 소식이 없으면 꺼진 것으로 본다


def _runner(r: EvalRunner) -> dict:
    online = r.last_seen is not None and (timezone.now() - r.last_seen).total_seconds() < RUNNER_ONLINE_SEC
    return {"enabled": r.enabled, "online": online, "last_seen": r.last_seen.isoformat() if r.last_seen else None}


def _job(j: SkillEvalJob) -> dict:
    return {"id": j.id, "batch": j.batch, "skills": j.skills, "case_ids": j.case_ids, "repeat": j.repeat,
            "model": j.model,
            "status": j.status, "total": j.total, "done": j.done, "error": j.error or None,
            "created_at": j.created_at.isoformat(),
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None}


@extend_schema(tags=["skills"], summary="스킬별 집계 (사용 기록 + 선택 평가)")
@api_view(["GET"])
def skill_list(request):
    try:
        days = int(request.query_params.get("days", 30))
    except ValueError as e:
        raise ApiError("days 는 정수여야 합니다") from e
    if not 1 <= days <= 365:
        raise ApiError("days 는 1~365 사이여야 합니다")
    data = stats.summary(request.query_params.get("batch") or None, days,
                         compare=request.query_params.get("compare") or None)
    active = SkillEvalJob.objects.filter(status__in=ACTIVE).first()
    data["job"] = _job(active) if active else None
    data["runner"] = _runner(EvalRunner.get())
    return Response(data)


@extend_schema(tags=["skills"], summary="스킬 사용 기록 저장 (훅이 보냄)")
@api_view(["POST"])
def skill_usage(request):
    saved = 0
    with transaction.atomic():
        for rec in _list(request.data, "records"):
            if not isinstance(rec, dict) or not rec.get("id") or not rec.get("skill"):
                raise ApiError("records 의 각 항목에는 id 와 skill 이 있어야 합니다")
            ok = rec.get("ok")
            SkillUsage.objects.update_or_create(source_id=str(rec["id"])[:100], defaults={
                "skill": str(rec["skill"])[:100], "repo": str(rec.get("repo") or "")[:100],
                "ok": ok if isinstance(ok, bool) else None,
                "duration_sec": _number(rec.get("duration_sec"), float),
                "input_tokens": _number(rec.get("input_tokens")), "output_tokens": _number(rec.get("output_tokens")),
                "tool_calls": _number(rec.get("tool_calls")), "tool_errors": _number(rec.get("tool_errors")),
                "used_at": _time(rec.get("used_at"), "used_at")})
            saved += 1
    return Response({"saved": saved}, status=201)


@extend_schema(tags=["skills"], summary="선택 평가 결과: 요청별 목록(GET), 실행 기록 저장(POST, run.py 가 보냄)")
@api_view(["GET", "POST"])
def skill_evals(request):
    if request.method == "GET":
        only = request.query_params.get("only", "failed")
        if only not in ("failed", "miss", "wrong", "all"):
            raise ApiError("only 는 failed, miss, wrong, all 중 하나입니다")
        return Response({"cases": stats.cases(request.query_params.get("batch") or None,
                                              request.query_params.get("skill") or None, only)})
    batch = request.data.get("batch")
    if not isinstance(batch, str) or not batch.strip():
        raise ApiError("batch 가 필요합니다")
    rows = _list(request.data, "rows")
    # 화면에서 정답을 바꾸거나 뺀 요청은 보낸 줄의 정답 대신 지금 정답으로 판정한다 (결과 파일에는 옛 정답이 남아 있다)
    known = {c.case_id: c for c in SkillEvalCase.objects.filter(
        case_id__in=[str(r.get("id")) for r in rows if isinstance(r, dict)])}
    saved = 0
    with transaction.atomic():
        for row in rows:
            if not isinstance(row, dict) or row.get("error"):
                continue  # 실행 자체가 실패한 줄은 결과가 아니다
            try:
                case_id, run, verdict = str(row["id"]), int(row["run"]), row["verdict"]
                fields = {k: str(row[k]) for k in ("skill", "kind", "split", "repo", "prompt", "model")}
            except (KeyError, TypeError, ValueError) as e:
                raise ApiError(f"rows 항목에 빠진 값이 있습니다: {e}") from e
            if verdict not in Verdict.values:
                raise ApiError(f"verdict 는 {', '.join(Verdict.values)} 중 하나입니다")
            expect, got = row.get("expect") or "", row.get("got") or ""
            case = known.get(case_id)
            if case and case.change == "remove":
                continue
            if case:
                expect, fields["kind"] = case.expect, case.kind
                verdict = stats.judge(expect, got)
            SkillEvalRun.objects.update_or_create(batch=batch.strip()[:100], case_id=case_id[:100], run=run, defaults={
                **fields, "verdict": verdict, "expect": expect, "got": got,
                "first_tool": row.get("first_tool") or "", "first_input": str(row.get("first_input") or "")[:300],
                "input_tokens": _number(row.get("input_tokens")) or 0,
                "sec": _number(row.get("sec"), float) or 0, "ran_at": _time(row.get("at"), "at")})
            saved += 1
    return Response({"saved": saved}, status=201)


@extend_schema(tags=["skills"], summary="평가 실행: 최근 목록(GET), 실행 요청(POST)")
@api_view(["GET", "POST"])
def eval_jobs(request):
    if request.method == "GET":
        return Response({"jobs": [_job(j) for j in SkillEvalJob.objects.all()[:10]]})
    d = request.data
    batch, model, skills = d.get("batch"), d.get("model", "sonnet"), d.get("skills") or []
    if not isinstance(batch, str) or not batch.strip():
        raise ApiError("batch 가 필요합니다")
    if "/" in batch or batch.startswith("."):
        raise ApiError("batch 에는 / 를 쓸 수 없습니다")  # 실행기가 파일 이름으로 쓴다
    if model not in MODELS:
        raise ApiError(f"model 은 {', '.join(MODELS)} 중 하나입니다")
    if not isinstance(skills, list) or not all(isinstance(s, str) and s for s in skills):
        raise ApiError("skills 는 스킬 이름 목록이어야 합니다")
    case_ids = d.get("case_ids") or []
    if not isinstance(case_ids, list) or not all(isinstance(c, str) and c for c in case_ids) or len(case_ids) > MAX_CASES:
        raise ApiError(f"case_ids 는 테스트 요청 id 목록(최대 {MAX_CASES}개)이어야 합니다")
    try:
        repeat = int(d.get("repeat", 1))
    except (TypeError, ValueError) as e:
        raise ApiError("repeat 는 정수여야 합니다") from e
    if not 1 <= repeat <= MAX_REPEAT:
        raise ApiError(f"repeat 는 1~{MAX_REPEAT} 사이여야 합니다")
    with transaction.atomic():
        if SkillEvalJob.objects.filter(status__in=ACTIVE).exists():
            raise ApiError("이미 대기 중이거나 실행 중인 평가가 있습니다", 409)
        job = SkillEvalJob.objects.create(batch=batch.strip()[:100], skills=[s.split(":")[-1] for s in skills],
                                          case_ids=case_ids, repeat=repeat, model=model)
    return Response(_job(job), status=201)


@extend_schema(tags=["skills"], summary="실행기 상태(GET), 평가 실행 허용 켜기·끄기(POST {enabled}, 화면에서)")
@api_view(["GET", "POST"])
def eval_runner(request):
    runner = EvalRunner.get()
    if request.method == "POST":
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            raise ApiError("enabled 는 true 또는 false 입니다")
        runner.enabled = enabled
        runner.save(update_fields=["enabled"])
    return Response(_runner(runner))


@extend_schema(tags=["skills"], summary="대기 중인 평가 실행 하나를 가져간다 (실행기 전용). 화면에서 실행 허용이 꺼져 있으면 안 준다")
@api_view(["POST"])
def eval_job_claim(request):
    with transaction.atomic():
        runner = EvalRunner.get()
        runner.last_seen = timezone.now()
        runner.save(update_fields=["last_seen"])
        job = None
        if runner.enabled:
            job = SkillEvalJob.objects.filter(status=JobStatus.QUEUED).order_by("id").first()
            if job:
                job.status, job.started_at = JobStatus.RUNNING, timezone.now()
                job.save(update_fields=["status", "started_at"])
    return Response({"job": _job(job) if job else None, "enabled": runner.enabled})


@extend_schema(tags=["skills"], summary="평가 실행 진행 상황 보고 (실행기 전용)")
@api_view(["POST"])
def eval_job_progress(request, pk: int):
    job = get_or_404(SkillEvalJob.objects, pk, JOB_NOT_FOUND)
    if job.status != JobStatus.RUNNING:  # 화면에서 중지했으면 실행기가 이 응답을 보고 멈춘다
        return Response(_job(job))
    d = request.data
    for key in ("total", "done"):
        if d.get(key) is not None:
            setattr(job, key, _number(d[key]) or 0)
    status = d.get("status")
    if status in (JobStatus.DONE, JobStatus.FAILED):
        job.status, job.finished_at, job.error = status, timezone.now(), str(d.get("error") or "")
    elif status is not None:
        raise ApiError("status 는 done 또는 failed 입니다")
    job.save()
    return Response(_job(job))


@extend_schema(tags=["skills"], summary="평가 실행 중지")
@api_view(["POST"])
def eval_job_cancel(request, pk: int):
    job = get_or_404(SkillEvalJob.objects, pk, JOB_NOT_FOUND)
    if job.status in ACTIVE:
        job.status, job.finished_at = JobStatus.CANCELLED, timezone.now()
        job.save(update_fields=["status", "finished_at"])
    return Response(_job(job))


def _case(c: SkillEvalCase) -> dict:
    return {"id": c.case_id, "skill": c.skill, "kind": c.kind, "split": c.split, "repo": c.repo,
            "prompt": c.prompt, "expect": c.expect or None, "origin": c.origin, "synced": c.synced,
            "change": c.change or None, "created_at": c.created_at.isoformat()}


def _case_fields(d) -> dict:
    """테스트 요청 하나의 값을 확인한다. 써야 하는 요청은 expect = skill, 쓰면 안 되는 요청은 다른 스킬이거나 없음."""
    if not isinstance(d, dict):
        raise ApiError("테스트 요청은 객체여야 합니다")
    f = {k: str(d.get(k) or "").strip() for k in CASE_FIELDS}
    missing = [k for k, v in f.items() if not v]
    if missing:
        raise ApiError(f"{', '.join(missing)} 가 필요합니다")
    if f["kind"] not in ("should", "should_not"):
        raise ApiError("kind 는 should 또는 should_not 입니다")
    if f["split"] not in ("train", "val"):
        raise ApiError("split 은 train 또는 val 입니다")
    if f["repo"] not in REPOS:
        raise ApiError(f"repo 는 {', '.join(REPOS)} 중 하나입니다")
    expect = str(d.get("expect") or "").strip()
    if f["kind"] == "should":
        expect = f["skill"]
    elif expect == f["skill"]:
        raise ApiError("쓰면 안 되는 요청의 기대 스킬은 시험하는 스킬과 달라야 합니다")
    return {**f, "expect": expect}


@extend_schema(tags=["skills"], summary="테스트 요청: 목록(GET), 화면에서 추가(POST)")
@api_view(["GET", "POST"])
def eval_cases(request):
    if request.method == "GET":
        qs = SkillEvalCase.objects.all()
        if request.query_params.get("skill"):
            qs = qs.filter(skill=request.query_params["skill"])
        if request.query_params.get("origin"):
            qs = qs.filter(origin=request.query_params["origin"])
        return Response({"cases": [_case(c) for c in qs]})
    fields = _case_fields(request.data)
    with transaction.atomic():
        if SkillEvalCase.objects.filter(prompt=fields["prompt"]).exists():
            raise ApiError("같은 문장의 테스트 요청이 이미 있습니다", 409)
        name = fields["skill"].split(":")[-1]
        taken = set(SkillEvalCase.objects.filter(case_id__startswith=f"{name}-u").values_list("case_id", flat=True))
        n = next(i for i in range(1, len(taken) + 2) if f"{name}-u{i}" not in taken)
        case = SkillEvalCase.objects.create(case_id=f"{name}-u{n}", origin="ui", synced=False, **fields)
    return Response(_case(case), status=201)


@extend_schema(tags=["skills"], summary="테스트 요청 정답 바꾸기·빼기 (화면에서). 이미 돌린 결과도 새 정답으로 다시 판정한다")
@api_view(["POST"])
def eval_case(request, case_id: str):
    case = SkillEvalCase.objects.filter(case_id=case_id).first()
    if case is None:
        raise Http404("테스트 요청을 찾을 수 없습니다")
    runs = SkillEvalRun.objects.filter(case_id=case_id)
    with transaction.atomic():
        if request.data.get("remove") is True:
            runs.delete()  # 뺀 요청은 모든 결과 이름의 집계에서 빠진다 (결과 파일에는 남는다)
            if case.synced:
                case.change = "remove"  # 실행기가 파일에서 지우면 목록에서도 빠진다
                case.save(update_fields=["change"])
            else:
                case.delete()  # 아직 파일에 안 옮긴 화면 추가분은 바로 지운다
            return Response({"id": case_id, "removed": True})
        if "expect" not in request.data:
            raise ApiError("expect 또는 remove 가 필요합니다")
        expect = str(request.data.get("expect") or "").strip()
        if expect and not expect.startswith(stats.PLUGIN):
            raise ApiError(f"expect 는 {stats.PLUGIN}<스킬> 이거나 빈칸(스킬 없음)이어야 합니다")
        case.expect, case.kind = expect, "should" if expect == case.skill else "should_not"
        if case.synced and case.change != "remove":
            case.change = "edit"
        case.save(update_fields=["expect", "kind", "change"])
        _rejudge(case_id, expect, case.kind)
    return Response(_case(case))


def _rejudge(case_id: str, expect: str, kind: str) -> None:
    """이 테스트 요청의 모든 실행을 새 정답으로 다시 판정한다 (모든 결과 이름)."""
    runs = list(SkillEvalRun.objects.filter(case_id=case_id))
    for r in runs:
        r.expect, r.kind, r.verdict = expect, kind, stats.judge(expect, r.got)
    SkillEvalRun.objects.bulk_update(runs, ["expect", "kind", "verdict"])


@extend_schema(tags=["skills"], summary="테스트 요청 맞추기 (실행기 전용): 파일의 요청을 받고, 파일에 없는 화면 추가분과 화면에서 바꾼 것을 돌려준다")
@api_view(["POST"])
def eval_cases_sync(request):
    cases, applied = request.data.get("cases"), request.data.get("applied") or []
    if not isinstance(cases, list) or not isinstance(applied, list):
        raise ApiError("cases 와 applied 는 목록이어야 합니다")
    with transaction.atomic():
        # 실행기가 파일에 반영했다고 알려 준 변경은 끝난 것으로 본다
        SkillEvalCase.objects.filter(case_id__in=[str(a) for a in applied]).update(change="")
        changed = set(SkillEvalCase.objects.exclude(change="").values_list("case_id", flat=True))
        ids = []
        for d in cases:
            fields = _case_fields(d)
            if not d.get("id"):
                raise ApiError("cases 의 각 항목에는 id 가 있어야 합니다")
            case_id = str(d["id"])[:100]
            ids.append(case_id)
            if case_id in changed:
                continue  # 파일은 아직 옛 값이다. 화면에서 바꾼 값을 지킨다
            before = SkillEvalCase.objects.filter(case_id=case_id).values_list("expect", "kind").first()
            if before is None:
                SkillEvalCase.objects.create(case_id=case_id, origin="file", synced=True, **fields)
                continue
            SkillEvalCase.objects.filter(case_id=case_id).update(synced=True, **fields)
            if before != (fields["expect"], fields["kind"]):
                _rejudge(case_id, fields["expect"], fields["kind"])  # 파일에서 정답을 바꿨으면 이미 돈 결과도 다시 판정
        # 파일에서 지운 요청은 목록에서도 뺀다. 화면에서 추가하고 아직 안 옮긴 것은 남긴다
        SkillEvalCase.objects.filter(synced=True).exclude(case_id__in=ids).delete()
        pending = [_case(c) for c in SkillEvalCase.objects.filter(synced=False)]
        changes = [_case(c) for c in SkillEvalCase.objects.filter(synced=True).exclude(change="")]
    return Response({"saved": len(ids), "pending": pending, "changes": changes})


def _try(t: SkillImproveTry) -> dict:
    return {"skill": t.skill, "try": t.try_no, "model": t.model, "cause": t.cause or None,
            "hypothesis": t.hypothesis, "change": t.change, "before_description": t.before_description,
            "description": t.description, "accepted": t.accepted, "reason": t.reason, "invalid": t.invalid or None,
            "scores": t.scores, "fixed": t.fixed, "broken": t.broken, "tried_at": t.tried_at.isoformat()}


SCORE_KEYS = ("train_before", "train_quick", "train_after", "val_before", "val_after", "others_before", "others_after")


@extend_schema(tags=["skills"], summary="설명 자동 개선 시도: 목록(GET), 저장(POST, improve.py 가 log.jsonl 을 통째로 보냄)")
@api_view(["GET", "POST"])
def improve_tries(request):
    if request.method == "GET":
        qs = SkillImproveTry.objects.all()
        if request.query_params.get("skill"):
            qs = qs.filter(skill=request.query_params["skill"])
        return Response({"tries": [_try(t) for t in qs]})
    saved = 0
    with transaction.atomic():
        for e in _list(request.data, "tries"):
            if not isinstance(e, dict) or not e.get("skill") or e.get("try") is None:
                raise ApiError("tries 의 각 항목에는 skill 과 try 가 있어야 합니다")
            ledger = e.get("ledger") if isinstance(e.get("ledger"), list) else []
            pick = lambda status: [x.get("prompt", "") for x in ledger if isinstance(x, dict) and x.get("status") == status]
            SkillImproveTry.objects.update_or_create(skill=str(e["skill"])[:100], try_no=int(e["try"]), defaults={
                "model": str(e.get("model") or "")[:50], "cause": str(e.get("cause") or "")[:20],
                **{k: str(e.get(k) or "") for k in ("hypothesis", "change", "before_description", "description",
                                                    "reason", "invalid")},
                "accepted": e.get("accepted") is True,
                "scores": {k: e[k] for k in SCORE_KEYS if isinstance(e.get(k), (int, float))},
                "fixed": pick("fixed"), "broken": pick("broken"), "tried_at": _time(e.get("at"), "at")})
            saved += 1
    return Response({"saved": saved}, status=201)
