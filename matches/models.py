"""세트 영상과 분석 결과 저장 (LoL). api 는 analyzer 가 만든 결과를 저장하고 돌려주기만 한다.

- GameVideo: 세트 영상 하나. analyzer 단계 결과(work/<stage>.json)와 경기 기본 정보(header)를 통째로 저장
- LineReview: 대사 원문 사람 검수
- Short: 숏폼
- Team·Match·MatchGame·GamePlayer: 예전에 api 가 op.gg 에서 직접 채우던 표. 경기 정보는 이제 analyzer header
  단계가 만들어 GameVideo.header 에 들어가므로 더 이상 채우지 않는다 (지울지 결정 전까지 남겨 둠)
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
