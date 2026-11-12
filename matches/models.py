"""경기 정보 (e스포츠). op.gg 경기 페이지에서 가져온다 (manage.py import_match).

- Team: 팀. op.gg 팀 id 로 구분
- Match: 경기 (BO3/BO5 하나). op.gg 경기 번호로 구분
- MatchGame: 세트. 영상 하나가 세트 하나에 대응한다
- GamePlayer: 세트별 진영·포지션·선수·챔피언. op.gg 페이지에 없어서 화면 OCR 이나 직접 입력으로 채운다
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
    work_name = models.CharField(max_length=200, unique=True)  # analyzer outputs/<이름>
    duration = models.FloatField(null=True, blank=True)
    hls_key = models.CharField(max_length=500, blank=True)
    analyze_status = models.CharField(max_length=10, choices=AnalyzeStatus.choices, default=AnalyzeStatus.PENDING)
    run_log = models.JSONField(default=list, blank=True)  # work/run_log.json
    results = models.JSONField(default=dict, blank=True)  # {stage: work/<stage>.json 전체}
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.title
