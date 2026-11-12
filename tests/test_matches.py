"""op.gg 경기 페이지 읽기와 저장 (네트워크 없이 페이지 HTML 을 흉내 낸다)."""

import json

from django.test import TestCase

from matches import opgg
from matches.management.commands.import_match import save_match
from matches.models import Match, MatchGame, Team

TEAM_BLG = {"id": "1", "name": "Bilibili Gaming", "acronym": "BLG", "imageUrl": "https://example.com/blg.png"}
TEAM_T1 = {"id": "2", "name": "T1", "acronym": "T1", "imageUrl": ""}
MATCH = {
    "id": "32706", "name": "Semifinal 1: BLG vs T1", "beginAt": "2026-11-08T22:07:29.000Z", "status": "finished",
    "numberOfGames": 5, "homeTeam": TEAM_BLG, "awayTeam": TEAM_T1, "winnerTeam": TEAM_BLG,
    "homeScore": 3, "awayScore": 1, "matchVersion": "16.22.1",
    "tournament": {"name": "Playoffs", "serie": {"year": 2026, "league": {"shortName": "Worlds"}}},
    "videos": [
        {"url": "https://youtu.be/a", "type": "full-game", "game": {"id": "36891", "set": 2}},
        {"url": "https://youtu.be/b", "type": "highlights", "game": {"id": "36891", "set": 2}},
        {"url": "https://youtu.be/c", "type": "full-game", "game": {"id": "36890", "set": 1}},
    ],
}


def page(match):
    data = {"props": {"pageProps": {"match": match}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


class OpggParseTest(TestCase):
    def test_match_url(self):
        self.assertEqual(opgg.match_url("32706"), "https://esports.op.gg/matches/32706")
        url = "https://esports.op.gg/matches/32706/blg-vs-t1-2026-11-09"
        self.assertEqual(opgg.match_url(url), url)
        with self.assertRaises(ValueError):
            opgg.match_url("https://example.com/matches/1")

    def test_parse_and_games(self):
        m = opgg.parse_match(page(MATCH))
        self.assertEqual(m["id"], "32706")
        games = opgg.games_from_videos(m)
        self.assertEqual(games[2], {"opgg_game_id": 36891, "full_video_url": "https://youtu.be/a",
                                    "highlight_url": "https://youtu.be/b"})
        self.assertEqual(games[1]["highlight_url"], "")

    def test_parse_without_data(self):
        with self.assertRaises(ValueError):
            opgg.parse_match("<html></html>")


class SaveMatchTest(TestCase):
    def test_save_and_overwrite(self):
        save_match("https://esports.op.gg/matches/32706", MATCH)
        m = Match.objects.get(opgg_id=32706)
        self.assertEqual((m.league, m.stage, m.year, m.best_of, m.patch), ("Worlds", "Playoffs", 2026, 5, "16.22.1"))
        self.assertEqual((m.home_team.acronym, m.home_score, m.away_score, m.winner.acronym), ("BLG", 3, 1, "BLG"))
        self.assertEqual(list(m.games.values_list("number", "opgg_game_id")), [(1, 36890), (2, 36891)])

        save_match("https://esports.op.gg/matches/32706", {**MATCH, "awayScore": 2})  # 다시 가져오면 덮어쓴다
        self.assertEqual(Match.objects.get(opgg_id=32706).away_score, 2)
        self.assertEqual((Match.objects.count(), Team.objects.count(), MatchGame.objects.count()), (1, 2, 2))
