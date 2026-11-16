"""Claude Code 스킬(esports-dev 플러그인) 사용 기록과 선택 평가 결과. 경기 데이터(matches)와는 무관하다.

- SkillUsage: 실제로 스킬이 불린 기록. dev-workflow 의 훅이 보낸다. 대화 내용은 담지 않는다
- SkillEvalCase: 선택 평가에 쓰는 테스트 요청. 기준은 dev-workflow 의 evals/cases/*.jsonl 이고, 화면에서 추가한 것은
  실행기가 그 파일에 옮겨 적는다
- SkillEvalRun: 선택 평가 실행 한 번 (테스트 요청 하나를 한 번 돌린 결과). dev-workflow 의 evals/run.py 가 보낸다
- SkillEvalJob: 화면에서 요청한 평가 실행. 맥에서 도는 실행기(evals/worker.py)가 가져가 돌린다
"""

from django.db import models


class SkillUsage(models.Model):
    source_id = models.CharField(max_length=100, unique=True)  # 훅이 만든 기록 id (다시 보내도 한 줄)
    skill = models.CharField(max_length=100, db_index=True)  # esports-dev:local-up
    repo = models.CharField(max_length=100, blank=True)  # 스킬을 부른 폴더 이름
    ok = models.BooleanField(null=True)  # 스킬을 부른 턴이 끝까지 갔는가 (모르면 null)
    duration_sec = models.FloatField(null=True, blank=True)  # 스킬 호출부터 그 턴이 끝날 때까지
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    tool_calls = models.PositiveIntegerField(null=True, blank=True)  # 스킬 호출 뒤 도구 호출 수
    tool_errors = models.PositiveIntegerField(null=True, blank=True)  # 그중 오류로 끝난 수
    used_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-used_at"]

    def __str__(self):
        return f"{self.skill} {self.used_at:%Y-%m-%d %H:%M}"


class Verdict(models.TextChoices):
    CORRECT = "correct"  # 기대한 스킬을 골랐거나, 기대가 없는데 고르지 않음
    MISS = "miss"        # 써야 하는데 안 씀 (누락)
    WRONG = "wrong"      # 다른 스킬을 고름 (오선택)


class SkillEvalRun(models.Model):
    batch = models.CharField(max_length=100, db_index=True)  # 평가 묶음 이름 (결과 파일 이름, 예: baseline-sonnet)
    case_id = models.CharField(max_length=100)  # add-endpoint-s2
    run = models.PositiveIntegerField()  # 같은 요청의 몇 번째 실행인가
    skill = models.CharField(max_length=100)  # 이 요청이 시험하는 스킬
    kind = models.CharField(max_length=20)  # should | should_not
    split = models.CharField(max_length=10)  # train | val
    repo = models.CharField(max_length=100)
    prompt = models.TextField()  # 테스트 요청 문장 (직접 쓴 것. 실제 대화가 아니다)
    expect = models.CharField(max_length=100, blank=True)  # 골라야 하는 스킬 (없으면 빈칸)
    got = models.CharField(max_length=100, blank=True)  # 고른 스킬 (없으면 빈칸)
    first_tool = models.CharField(max_length=100, blank=True)  # 첫 도구 호출 이름 (Skill, Bash …)
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    model = models.CharField(max_length=50)
    input_tokens = models.PositiveIntegerField(default=0)
    sec = models.FloatField(default=0)
    ran_at = models.DateTimeField()

    class Meta:
        ordering = ["batch", "case_id", "run"]
        constraints = [models.UniqueConstraint(fields=["batch", "case_id", "run"], name="uniq_eval_run")]

    def __str__(self):
        return f"{self.batch} {self.case_id} #{self.run}"


class JobStatus(models.TextChoices):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE = [JobStatus.QUEUED, JobStatus.RUNNING]


class SkillEvalJob(models.Model):
    batch = models.CharField(max_length=100)  # 결과를 쌓을 평가 묶음
    skills = models.JSONField(default=list, blank=True)  # 접두어 없는 스킬 이름 목록. 비면 전체
    repeat = models.PositiveIntegerField(default=1)  # 요청마다 몇 번까지 채울지
    model = models.CharField(max_length=50, default="sonnet")
    status = models.CharField(max_length=10, choices=JobStatus.choices, default=JobStatus.QUEUED)
    total = models.PositiveIntegerField(default=0)  # 이번에 돌릴 실행 수 (실행기가 채운다)
    done = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"job {self.id} {self.batch} {self.status}"


class SkillEvalCase(models.Model):
    case_id = models.CharField(max_length=100, unique=True)  # add-endpoint-s2, 화면에서 추가한 것은 add-endpoint-u1
    skill = models.CharField(max_length=100, db_index=True)  # 이 요청이 시험하는 스킬
    kind = models.CharField(max_length=20)  # should (써야 함) | should_not (쓰면 안 됨)
    split = models.CharField(max_length=10)  # train (개선용) | val (검증용)
    repo = models.CharField(max_length=100)
    prompt = models.TextField()
    expect = models.CharField(max_length=100, blank=True)  # 골라야 하는 스킬 (없으면 빈칸)
    origin = models.CharField(max_length=10, default="file")  # file | ui
    synced = models.BooleanField(default=True)  # evals/cases 파일에 들어 있는가 (화면에서 추가하면 실행기가 옮길 때까지 False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["skill", "case_id"]

    def __str__(self):
        return self.case_id
