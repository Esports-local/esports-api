"""데이터 모델. 필드는 스펙 시트(호출 목록, series, episodes 탭)를 따른다.

- 작품·회차·등장인물은 크롤링(TMDB)으로 채운다. api 는 조회만 한다.
- main 분석 결과(episode.json)는 Episode.analysis 에 통째로 저장한다 (스키마 미확정).
- 예측은 (작품, target) 마다 하나. 다시 요청하면 덮어쓴다.
"""

from django.db import models


class JobStatus(models.TextChoices):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Series(models.Model):
    tmdb_id = models.PositiveIntegerField(unique=True)
    title = models.CharField(max_length=200)
    synopsis = models.TextField(blank=True)
    poster = models.URLField(max_length=500, blank=True)
    first_air_date = models.DateField(null=True, blank=True)
    episode_count = models.PositiveIntegerField(default=0)  # TMDB 기준 전체 회차 수
    genres = models.JSONField(default=list, blank=True)  # ["드라마", …]
    crew = models.JSONField(default=list, blank=True)  # [{"name", "job"}]
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "series"

    def __str__(self):
        return self.title


class Episode(models.Model):
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name="episodes")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200, blank=True)
    synopsis = models.TextField(blank=True)
    air_date = models.DateField(null=True, blank=True)
    still = models.URLField(max_length=500, blank=True)

    # 영상 (MinIO key 만 저장)
    video_key = models.CharField(max_length=500, blank=True)  # raw/{id}/source.mp4
    hls_key = models.CharField(max_length=500, blank=True)  # hls/{id}/master.m3u8

    # 분석 (main)
    analyze_status = models.CharField(max_length=10, choices=JobStatus.choices, default=JobStatus.IDLE)
    duration = models.FloatField(null=True, blank=True)
    analysis = models.JSONField(null=True, blank=True)  # main episode.json
    schema_version = models.PositiveIntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["series_id", "number"]
        constraints = [models.UniqueConstraint(fields=["series", "number"], name="uniq_episode_number")]

    def __str__(self):
        return f"{self.series} {self.number}화"

    @property
    def has_video(self) -> bool:
        return bool(self.video_key or self.hls_key)


class Character(models.Model):
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name="characters")
    tmdb_person_id = models.PositiveIntegerField(null=True, blank=True)
    name = models.CharField(max_length=200)  # 배역
    actor = models.CharField(max_length=200, blank=True)
    photo = models.URLField(max_length=500, blank=True)
    aliases = models.JSONField(default=list, blank=True)  # 직접 입력
    order = models.PositiveIntegerField(default=0)  # 출연 순

    class Meta:
        ordering = ["series_id", "order", "id"]

    def __str__(self):
        return f"{self.name} ({self.actor})"


class Prediction(models.Model):
    series = models.ForeignKey(Series, on_delete=models.CASCADE, related_name="predictions")
    target = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=JobStatus.choices, default=JobStatus.QUEUED)
    used_episodes = models.JSONField(default=list, blank=True)
    items = models.JSONField(default=list, blank=True)  # LLM 결과 (스키마 미확정)
    schema_version = models.PositiveIntegerField(default=1)
    error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["series", "target"], name="uniq_prediction_target")]

    def __str__(self):
        return f"{self.series} → {self.target}화 ({self.status})"


class Verdict(models.TextChoices):
    OK = "ok"  # 맞음
    WRONG = "wrong"  # 틀림
    FIXED = "fixed"  # 수정 (text 에 고친 대사)


class LineReview(models.Model):
    """대사 하나의 검수 판정. 대사는 (장면 id, 장면 안 순서 index)로 가리킨다.

    index 는 Episode.analysis 의 scenes[].lines 순서라서, 회차를 다시 분석하면
    그 회차의 LineReview 를 모두 지워야 한다 (분석 결과 저장 코드에서 처리).
    """

    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="line_reviews")
    scene_id = models.PositiveIntegerField()
    index = models.PositiveIntegerField()
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    text = models.TextField(blank=True)  # fixed 일 때만
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["episode_id", "scene_id", "index"]
        constraints = [
            models.UniqueConstraint(fields=["episode", "scene_id", "index"], name="uniq_line_review"),
        ]

    def __str__(self):
        return f"{self.episode} 장면{self.scene_id}#{self.index} {self.verdict}"
