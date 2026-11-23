"""선수 이름 사전(matches/players_ko.py)을 Player 표에 넣는다. api 컨테이너를 띄울 때 자동 실행 (docker-compose).

- 사전의 선수: 없으면 만들고, 한국어 표기는 사전 값으로 맞춘다 (사전이 기준)
- 세트 영상 경기 정보(header)의 선수: 없으면 이름만 만들고 팀을 맞춘다
- 경기 정보에 나왔는데 사전에 없는 선수를 알려 준다 → players_ko.py 에 추가

    python manage.py sync_players
"""

from django.core.management.base import BaseCommand

from matches.models import GameVideo, Player
from matches.players_ko import PLAYERS_KO


def sync(players_ko: dict[str, str] | None = None) -> dict:
    """{added, updated, missing: [사전에 없는 경기 선수]}"""
    players_ko = PLAYERS_KO if players_ko is None else players_ko
    added = updated = 0
    for name, ko in players_ko.items():
        obj = Player.objects.filter(name__iexact=name).first()
        if obj is None:
            Player.objects.create(name=name, name_ko=ko)
            added += 1
        elif obj.name_ko != ko:
            obj.name_ko = ko
            obj.save(update_fields=["name_ko", "updated_at"])
            updated += 1
    for v in GameVideo.objects.exclude(header={}):
        teams = {side: (t or {}).get("name", "") for side, t in ((v.header or {}).get("teams") or {}).items()}
        for p in (v.header or {}).get("players") or []:
            if not p.get("name"):
                continue
            obj = Player.objects.filter(name__iexact=p["name"]).first()
            if obj is None:
                obj = Player.objects.create(name=p["name"])
                added += 1
            team = teams.get(p.get("side"), "")
            if team and obj.team != team:
                obj.team = team
                obj.save(update_fields=["team", "updated_at"])
    missing = list(Player.objects.filter(name_ko="").values_list("name", flat=True))
    return {"added": added, "updated": updated, "missing": missing}


class Command(BaseCommand):
    help = "선수 이름 사전(players_ko.py)을 Player 표에 넣고, 사전에 없는 경기 선수를 알려 준다"

    def handle(self, *args, **options):
        r = sync()
        self.stdout.write(f"선수 사전: 추가 {r['added']}, 한국어 표기 바뀜 {r['updated']}, 전체 {Player.objects.count()}"
                          + (f" · 사전에 없음(players_ko.py 에 추가): {', '.join(r['missing'])}" if r["missing"] else ""))
