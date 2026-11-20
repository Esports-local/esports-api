"""경기 정보 (e스포츠). op.gg 경기 페이지에서 가져온다 (manage.py import_match).

- Team: 팀. op.gg 팀 id 로 구분
- Match: 경기 (BO3/BO5 하나). op.gg 경기 번호로 구분
- MatchGame: 세트. 영상 하나가 세트 하나에 대응한다
- GamePlayer: 세트별 진영·포지션·선수·챔피언. import_match 가 op.gg 세트 정보(GetGameByMatch)로 채우고,
  못 채운 칸만 import_outputs 가 화면 OCR 로 채운다. 선수 한글 표기(name_ko)는 직접 입력
"""

from django.db import models


class Side(models.TextChoices):
    BLUE = "blue"
    RED = "red"


class Role(models.TextChoices):
    TOP = "top"
    JUNGLE = "jungle"
    MID = "mid"
    BOT = "bot"
    SUPPORT = "support"


class Team(models.Model):
    opgg_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=100)  # Bilibili Gaming
    acronym = models.CharField(max_length=20)  # BLG
    image_url = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["acronym"]

    def __str__(self):
        return self.acronym


class Match(models.Model):
    opgg_id = models.PositiveIntegerField(unique=True)  # esports.op.gg/matches/<번호>
    name = models.CharField(max_length=200)  # Semifinal 1: BLG vs T1
    league = models.CharField(max_length=50, blank=True)  # Worlds
    stage = models.CharField(max_length=100, blank=True)  # Playoffs
    year = models.PositiveIntegerField(null=True, blank=True)
    begin_at = models.DateTimeField(null=True, blank=True)  # 실제 시작 (UTC). 안 했으면 예정 시각
    status = models.CharField(max_length=20, blank=True)  # not_started | running | finished
    best_of = models.PositiveIntegerField(default=1)
    home_team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="home_matches")
    away_team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="away_matches")
    home_score = models.PositiveIntegerField(default=0)
    away_score = models.PositiveIntegerField(default=0)
    winner = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True, related_name="won_matches")
    patch = models.CharField(max_length=20, blank=True)  # 16.22.1
    source_url = models.URLField(max_length=500)
    raw = models.JSONField(default=dict, blank=True)  # 가져온 원본 (나중에 필드 추가할 때 다시 안 받도록)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-begin_at"]

    def __str__(self):
        return self.name


class MatchGame(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="games")
    number = models.PositiveIntegerField()  # 세트 번호 (1부터)
    opgg_game_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    full_video_url = models.URLField(max_length=500, blank=True)
    highlight_url = models.URLField(max_length=500, blank=True)
    # 페이지에 없음 → 화면 OCR·직접 입력
    blue_team = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    red_team = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    winner = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    bans = models.JSONField(default=dict, blank=True)  # {"blue": ["Galio", …], "red": […]} 챔피언 영어 이름 (op.gg)

    class Meta:
        ordering = ["match_id", "number"]
        constraints = [models.UniqueConstraint(fields=["match", "number"], name="uniq_match_game_number")]

    def __str__(self):
        return f"{self.match} {self.number}세트"

    def has_opgg_lineup(self) -> bool:
        """op.gg 세트 정보로 선수가 채워졌는지. 챔피언은 op.gg 에서만 오므로 챔피언이 있는 선수가 있으면 op.gg 값."""
        return self.players.exclude(champion="").exists()


class GamePlayer(models.Model):
    game = models.ForeignKey(MatchGame, on_delete=models.CASCADE, related_name="players")
    side = models.CharField(max_length=4, choices=Side.choices)
    role = models.CharField(max_length=10, choices=Role.choices)
    name = models.CharField(max_length=50)  # Keria
    name_ko = models.CharField(max_length=50, blank=True)  # 케리아 (해설 표기, 선택)
    champion = models.CharField(max_length=50, blank=True)  # Poppy
    champion_ko = models.CharField(max_length=50, blank=True)  # 뽀삐

    class Meta:
        ordering = ["game_id", "side", "role"]
        constraints = [models.UniqueConstraint(fields=["game", "side", "role"], name="uniq_game_side_role")]

    def __str__(self):
        return f"{self.game} {self.side} {self.role} {self.name}"


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
    game = models.ForeignKey(MatchGame, on_delete=models.SET_NULL, null=True, blank=True, related_name="videos")
    work_name = models.CharField(max_length=200, unique=True)  # analyzer outputs/<이름> (영상 파일 이름에서 확장자 뺀 것)
    video_name = models.CharField(max_length=300, blank=True)  # analyzer VIDEOS_ROOT 의 원본 파일 이름
    job_id = models.CharField(max_length=100, blank=True)  # 진행 중이거나 마지막 analyzer 작업
    error = models.TextField(blank=True)  # 마지막 작업이 실패한 이유
    duration = models.FloatField(null=True, blank=True)
    hls_key = models.CharField(max_length=500, blank=True)
    analyze_status = models.CharField(max_length=10, choices=AnalyzeStatus.choices, default=AnalyzeStatus.PENDING)
    run_log = models.JSONField(default=list, blank=True)  # work/run_log.json
    results = models.JSONField(default=dict, blank=True)  # {stage: work/<stage>.json 전체}
    header = models.JSONField(default=dict, blank=True)  # 경기 기본 정보 (matches/header.py, 세트가 있을 때 자동)
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
    subtitles = models.CharField(max_length=4, default="ko")  # ko | en | none
    title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=ShortStatus.choices, default=ShortStatus.QUEUED)
    storage_key = models.CharField(max_length=300, blank=True)  # shorts/<key>.mp4 (done 일 때)
    render_sec = models.FloatField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.video.work_name} {self.key} ({self.status})"
