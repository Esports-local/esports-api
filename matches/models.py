"""세트 영상과 분석 결과 저장 (LoL). api 는 analyzer 가 만든 결과를 저장하고 돌려주기만 한다.

- GameVideo: 세트 영상 하나. analyzer 단계 결과(work/<stage>.json)와 경기 기본 정보(header)를 통째로 저장
- LineReview: 대사 원문 사람 검수
- Short: 숏폼
- Player: 선수 이름 사전 (영어 → 한국어)
- CutReview: 장면 전환 사람 검수 (통과·불통)
경기 정보는 analyzer header 단계가 만들어 GameVideo.header 에 들어간다 (예전 Team·Match·MatchGame·GamePlayer 표는 11-23 삭제)
"""

from django.db import models


class Player(models.Model):
    """선수 이름 사전: 영어 이름(op.gg·header) → 한국어 표기. 숏폼 자막을 만들 때 바꿔 쓴다 (Faker → 페이커).

    내용은 코드(matches/players_ko.py)가 기준이고 sync_players 가 넣는다 (손으로 고치지 않음).
    name 은 대소문자를 가리지 않고 찾는다. name_ko 가 비어 있으면 영어 그대로 쓴다.
    """

    name = models.CharField(max_length=50, unique=True)      # Faker
    name_ko = models.CharField(max_length=50, blank=True)    # 페이커
    team = models.CharField(max_length=20, blank=True)       # 참고용 (T1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["team", "name"]

    def __str__(self):
        return f"{self.name} → {self.name_ko or '?'}"

    @staticmethod
    def ko_map() -> dict[str, str]:
        """{영어 이름 소문자: 한국어} (한국어가 있는 것만)."""
        return {p.name.lower(): p.name_ko for p in Player.objects.exclude(name_ko="")}


class AnalyzeStatus(models.TextChoices):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class GameVideo(models.Model):
    """세트 영상 하나 (해설 언어별로 따로). analyzer 결과(work/<stage>.json)를 통째로 저장한다.

    스펙 시트의 /games 가 이 모델이다. 결과는 manage.py import_outputs 로 넣는다.
    """

    title = models.CharField(max_length=200)
    language = models.CharField(max_length=5, default="ko")  # 해설 언어 ko | en
    work_name = models.CharField(max_length=200, unique=True)  # analyzer outputs/<이름> (영상 파일 이름에서 확장자 뺀 것)
    video_name = models.CharField(max_length=300, blank=True)  # analyzer VIDEOS_ROOT 의 원본 파일 이름 (분석 대상)
    # 재생·숏폼 렌더에 쓰는 원본 파일 이름 (video_url). 구간 분석 폴더(<영상>_900-1500s)를 넣을 때 쓴다.
    # video_name 에 넣으면 "분석 다시 실행"이 구간이 아니라 원본 전체를 분석하므로 따로 둔다
    playback_name = models.CharField(max_length=300, blank=True)
    job_id = models.CharField(max_length=100, blank=True)  # 진행 중이거나 마지막 analyzer 작업
    error = models.TextField(blank=True)  # 마지막 작업이 실패한 이유
    duration = models.FloatField(null=True, blank=True)
    analyze_status = models.CharField(max_length=10, choices=AnalyzeStatus.choices, default=AnalyzeStatus.PENDING)
    run_log = models.JSONField(default=list, blank=True)  # work/run_log.json
    results = models.JSONField(default=dict, blank=True)  # {stage: work/<stage>.json 전체}
    opgg_match = models.PositiveIntegerField(null=True, blank=True)  # op.gg 경기 번호 (영상 등록 때 받아 analyzer header 단계에 넘김)
    set_number = models.PositiveIntegerField(null=True, blank=True)  # 세트 번호
    header = models.JSONField(default=dict, blank=True)  # analyzer work/header.json 의 result (경기 기본 정보)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.title


class LineReview(models.Model):
    """해설 대사 하나의 사람 검수. analyzer 결과(GameVideo.results)와 따로 두어 분석을 다시 돌려도 남는다.

    - text: 사람이 고친 문장. 비어 있으면 ASR 원문 그대로 (안 고침). 번역할 때 ASR 원문 대신 쓴다
    - reviewed: 검수했는지 (화면의 O / X)
    - asr_text: 검수할 때의 ASR 원문. 지금 ASR 원문과 다르면 (asr 를 다시 돌림) 이 검수는 쓰지 않는다
    """

    video = models.ForeignKey(GameVideo, on_delete=models.CASCADE, related_name="reviews")
    line_id = models.PositiveIntegerField()  # asr 대사 id
    asr_text = models.TextField()
    text = models.TextField(blank=True)
    reviewed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["video", "line_id"]
        constraints = [models.UniqueConstraint(fields=["video", "line_id"], name="unique_line_review")]

    def __str__(self):
        return f"{self.video_id}#{self.line_id}"


class CutReview(models.Model):
    """장면 전환(segments 단계 transition) 하나의 사람 검수: 통과(pass) · 불통(fail).

    analyzer 결과와 따로 두어 분석을 다시 돌려도 남는다. 검수할 때의 전환 시각·종류를 같이 저장하고,
    segments 를 다시 돌려 같은 번호의 전환 시각(0.05초)이나 종류가 바뀌었으면 이 검수는 쓰지 않는다.
    """

    class Verdict(models.TextChoices):
        PASS = "pass"
        FAIL = "fail"

    video = models.ForeignKey(GameVideo, on_delete=models.CASCADE, related_name="cut_reviews")
    transition_id = models.PositiveIntegerField()
    start_sec = models.FloatField()
    kind = models.CharField(max_length=10)  # cut · dissolve · wipe
    verdict = models.CharField(max_length=4, choices=Verdict.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["video_id", "transition_id"]
        constraints = [models.UniqueConstraint(fields=["video", "transition_id"], name="uniq_cut_review")]


class ShortStatus(models.TextChoices):
    QUEUED = "queued"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"


class Short(models.Model):
    """세로(9:16) 숏폼 하나. 렌더는 analyzer 가 하고, 끝나면 mp4 를 저장소(shorts/<key>.mp4)에 올린다.

    key 는 입력(영상 결과 버전, 구간, 자막 문장, 제목)의 해시라 같은 요청은 같은 행을 쓴다 (다시 렌더하지 않음).
    """

    video = models.ForeignKey(GameVideo, on_delete=models.CASCADE, related_name="shorts")
    key = models.CharField(max_length=64, unique=True)
    event_ids = models.JSONField(default=list)
    segments = models.JSONField(default=list)  # [{start_sec, end_sec}] 원본 기준, 합친 뒤
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=ShortStatus.choices, default=ShortStatus.QUEUED)
    storage_key = models.CharField(max_length=300, blank=True)  # shorts/<key>.mp4 (done 일 때)
    render_sec = models.FloatField(null=True, blank=True)
    bgm = models.JSONField(default=dict, blank=True)  # 깐 BGM {title, source, license, attribution} (analyzer 렌더 기록)
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.video.work_name} {self.key} ({self.status})"
