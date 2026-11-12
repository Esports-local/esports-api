"""op.gg 경기 페이지에서 경기·팀·세트를 가져와 저장한다. 같은 경기는 덮어쓴다.

    python manage.py import_match 32706
    python manage.py import_match https://esports.op.gg/matches/32706/blg-vs-t1-2026-11-09
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from matches import opgg
from matches.models import Match, MatchGame, Team


class Command(BaseCommand):
    help = "op.gg 경기 번호(또는 주소)로 경기 정보를 가져와 저장한다"

    def add_arguments(self, parser):
        parser.add_argument("refs", nargs="+", help="op.gg 경기 번호나 경기 페이지 주소")

    def handle(self, *args, refs, **options):
        for ref in refs:
            try:
                url, data = opgg.fetch_match(ref)
            except (ValueError, OSError) as e:
                raise CommandError(f"{ref}: {e}") from e
            match = save_match(url, data)
            games = ", ".join(f"{g.number}세트({g.opgg_game_id})" for g in match.games.all())
            self.stdout.write(self.style.SUCCESS(
                f"{match.opgg_id} {match.name} | {match.home_team} {match.home_score}:{match.away_score} "
                f"{match.away_team} | {match.begin_at} | 세트 {games or '없음'}"))


def save_team(t: dict) -> Team:
    team, _ = Team.objects.update_or_create(
        opgg_id=int(t["id"]),
        defaults={"name": t.get("name") or "", "acronym": t.get("acronym") or t.get("name") or "",
                  "image_url": t.get("imageUrl") or ""})
    return team


@transaction.atomic
def save_match(url: str, d: dict) -> Match:
    """op.gg match JSON 을 Team·Match·MatchGame 으로 저장한다."""
    home, away = save_team(d["homeTeam"]), save_team(d["awayTeam"])
    winner = save_team(d["winnerTeam"]) if d.get("winnerTeam") else None
    tour = d.get("tournament") or {}
    serie = tour.get("serie") or {}
    match, _ = Match.objects.update_or_create(
        opgg_id=int(d["id"]),
        defaults={"name": d.get("name") or "", "league": (serie.get("league") or {}).get("shortName") or "",
                  "stage": tour.get("name") or "", "year": serie.get("year"),
                  "begin_at": parse_datetime(d.get("beginAt") or d.get("scheduledAt") or ""),
                  "status": d.get("status") or "", "best_of": d.get("numberOfGames") or 1,
                  "home_team": home, "away_team": away, "home_score": d.get("homeScore") or 0,
                  "away_score": d.get("awayScore") or 0, "winner": winner,
                  "patch": d.get("matchVersion") or "", "source_url": url, "raw": d})
    for number, g in sorted(opgg.games_from_videos(d).items()):
        MatchGame.objects.update_or_create(match=match, number=number, defaults=g)
    return match
