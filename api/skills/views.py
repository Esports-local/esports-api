"""/skills 엔드포인트: 스킬 사용 기록, 선택 평가 결과, 화면에서 요청하는 평가 실행.

기록을 보내는 쪽은 dev-workflow 레포다 (사용 기록 = 훅, 평가 결과 = evals/run.py, 평가 실행 = evals/worker.py).
"""

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.exceptions import ApiError, get_or_404
from skills import stats
from skills.models import ACTIVE, JobStatus, SkillEvalCase, SkillEvalJob, SkillEvalRun, SkillUsage, Verdict

MODELS = ["sonnet", "haiku"]  # 평가에 쓸 수 있는 모델 (기본 모델로 돌지 않게 고정)
MAX_REPEAT = 5
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


def _job(j: SkillEvalJob) -> dict:
    return {"id": j.id, "batch": j.batch, "skills": j.skills, "repeat": j.repeat, "model": j.model,
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
    data = stats.summary(request.query_params.get("batch") or None, days)
    active = SkillEvalJob.objects.filter(status__in=ACTIVE).first()
    data["job"] = _job(active) if active else None
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
    saved = 0
    with transaction.atomic():
        for row in _list(request.data, "rows"):
            if not isinstance(row, dict) or row.get("error"):
                continue  # 실행 자체가 실패한 줄은 결과가 아니다
            try:
                case_id, run, verdict = str(row["id"]), int(row["run"]), row["verdict"]
                fields = {k: str(row[k]) for k in ("skill", "kind", "split", "repo", "prompt", "model")}
            except (KeyError, TypeError, ValueError) as e:
                raise ApiError(f"rows 항목에 빠진 값이 있습니다: {e}") from e
            if verdict not in Verdict.values:
                raise ApiError(f"verdict 는 {', '.join(Verdict.values)} 중 하나입니다")
            SkillEvalRun.objects.update_or_create(batch=batch.strip()[:100], case_id=case_id[:100], run=run, defaults={
                **fields, "verdict": verdict, "expect": row.get("expect") or "", "got": row.get("got") or "",
                "first_tool": row.get("first_tool") or "", "input_tokens": _number(row.get("input_tokens")) or 0,
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
                                          repeat=repeat, model=model)
    return Response(_job(job), status=201)


@extend_schema(tags=["skills"], summary="대기 중인 평가 실행 하나를 가져간다 (실행기 전용)")
@api_view(["POST"])
def eval_job_claim(request):
    with transaction.atomic():
        job = SkillEvalJob.objects.filter(status=JobStatus.QUEUED).order_by("id").first()
        if job:
            job.status, job.started_at = JobStatus.RUNNING, timezone.now()
            job.save(update_fields=["status", "started_at"])
    return Response({"job": _job(job) if job else None})


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
            "created_at": c.created_at.isoformat()}


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


@extend_schema(tags=["skills"], summary="테스트 요청 맞추기 (실행기 전용): 파일의 요청을 받고, 파일에 없는 화면 추가분을 돌려준다")
@api_view(["POST"])
def eval_cases_sync(request):
    cases = request.data.get("cases")
    if not isinstance(cases, list):
        raise ApiError("cases 는 목록이어야 합니다")
    with transaction.atomic():
        ids = []
        for d in cases:
            fields = _case_fields(d)
            if not d.get("id"):
                raise ApiError("cases 의 각 항목에는 id 가 있어야 합니다")
            case_id = str(d["id"])[:100]
            ids.append(case_id)
            if not SkillEvalCase.objects.filter(case_id=case_id).update(synced=True, **fields):
                SkillEvalCase.objects.create(case_id=case_id, origin="file", synced=True, **fields)
        # 파일에서 지운 요청은 목록에서도 뺀다. 화면에서 추가하고 아직 안 옮긴 것은 남긴다
        SkillEvalCase.objects.filter(synced=True).exclude(case_id__in=ids).delete()
        pending = [_case(c) for c in SkillEvalCase.objects.filter(synced=False)]
    return Response({"saved": len(ids), "pending": pending})
