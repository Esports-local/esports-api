"""op.gg 경기 페이지 읽기와 저장 (네트워크 없이 페이지 HTML 을 흉내 낸다)."""

import json

from django.test import TestCase

from unittest import mock

from matches import ddragon, opgg
from matches.header import build_header
from matches.lineups import save_lineup
from matches.management.commands.import_match import save_match
from matches.models import GamePlayer, Match, MatchGame, Team
from matches.outputs import fill_game_from_screen

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


# op.gg GetGameByMatch 응답 (2세트, 일부 선수만)
GAME = {
    "id": "36891",
    "winner": {"id": "2"},
    "teams": [{"side": "blue", "bans": [3, 24], "team": {"id": "2", "acronym": "T1"}},
              {"side": "red", "bans": [1], "team": {"id": "1", "acronym": "BLG"}}],
    "players": [
        {"side": "blue", "position": "sup", "championId": "78", "player": {"nickName": "Keria"}},
        {"side": "red", "position": "jun", "championId": "246", "player": {"nickName": "XUN"}},
        {"side": "red", "position": "coach", "championId": "1", "player": {"nickName": "?"}},
    ],
}
CHAMPS = {"78": {"id": "Poppy", "name": "Poppy", "ko": "뽀삐"}, "246": {"id": "Qiyana", "name": "Qiyana", "ko": "키아나"},
          "1": {"id": "Annie", "name": "Annie", "ko": "애니"}, "3": {"id": "Galio", "name": "Galio", "ko": "갈리오"},
          "24": {"id": "Jax", "name": "Jax", "ko": "잭스"}, "202": {"id": "Jhin", "name": "Jhin", "ko": "진"}}
# 1세트: BLG 블루·승, T1 Keria 진(Jhin)
GAME1 = {"id": "36890", "winner": {"id": "1"},
         "teams": [{"side": "blue", "bans": [24], "team": {"id": "1"}}, {"side": "red", "bans": [], "team": {"id": "2"}}],
         "players": [{"side": "red", "position": "sup", "championId": "202", "player": {"nickName": "Keria"}}]}


class LineupTest(TestCase):
    def test_parse_game(self):
        g = opgg.parse_game(GAME)
        self.assertEqual((g["opgg_game_id"], g["winner"], g["sides"], g["bans"]),
                         (36891, 2, {"blue": 2, "red": 1}, {"blue": ["3", "24"], "red": ["1"]}))
        self.assertEqual(g["players"], [  # 포지션 이름을 GamePlayer.role 로, 모르는 포지션은 뺀다
            {"side": "blue", "role": "support", "name": "Keria", "champion_id": "78"},
            {"side": "red", "role": "jungle", "name": "XUN", "champion_id": "246"}])

    def test_save_lineup_keeps_name_ko(self):
        match = save_match("https://esports.op.gg/matches/32706", MATCH)
        game = match.games.get(number=2)
        GamePlayer.objects.create(game=game, side="red", role="jungle", name="Xun", name_ko="쑨")
        save_lineup(match, 2, opgg.parse_game(GAME), CHAMPS)
        game.refresh_from_db()
        self.assertEqual((game.blue_team.acronym, game.red_team.acronym, game.winner.acronym), ("T1", "BLG", "T1"))
        self.assertEqual(game.bans, {"blue": ["Galio", "Jax"], "red": ["Annie"]})
        rows = list(game.players.values_list("side", "role", "name", "name_ko", "champion", "champion_ko"))
        self.assertEqual(rows, [("blue", "support", "Keria", "", "Poppy", "뽀삐"),
                                ("red", "jungle", "XUN", "쑨", "Qiyana", "키아나")])

    def test_screen_does_not_overwrite_opgg(self):
        match = save_match("https://esports.op.gg/matches/32706", MATCH)
        save_lineup(match, 2, opgg.parse_game(GAME), CHAMPS)
        game = match.games.get(number=2)
        runs = [  # OCR 이 팀을 반대로, 선수 이름을 잘못 읽은 경우
            {"tag": "team", "slot": "blue", "text": "BLG", "start_sec": 0, "end_sec": 900, "samples": 50},
            {"tag": "team", "slot": "red", "text": "T1", "start_sec": 0, "end_sec": 900, "samples": 50},
            {"tag": "player_name", "slot": "blue_support", "text": "Kerla", "start_sec": 0, "end_sec": 900,
             "samples": 50},
            {"tag": "player_name", "slot": "blue_top", "text": "Doran", "start_sec": 0, "end_sec": 900,
             "samples": 50},
        ]
        fill_game_from_screen(game, runs)
        game.refresh_from_db()
        self.assertEqual(game.blue_team.acronym, "T1")
        self.assertEqual(dict(game.players.values_list("role", "name")),
                         {"support": "Keria", "jungle": "XUN", "top": "Doran"})  # 빈 칸(top)만 OCR 로 채움

    @mock.patch("matches.ddragon.skills", side_effect=lambda v, cid: {"Q": f"{cid}-Q"})
    @mock.patch("matches.ddragon.version_for", return_value="16.22.1")
    def test_build_header_fearless(self, _version, _skills):
        match = save_match("https://esports.op.gg/matches/32706", MATCH)
        save_lineup(match, 1, opgg.parse_game(GAME1), CHAMPS)
        save_lineup(match, 2, opgg.parse_game(GAME), CHAMPS)
        with mock.patch("matches.ddragon.champions", return_value=CHAMPS):
            h = build_header(match.games.get(number=2))
        self.assertEqual(h["match"]["set"], 2)
        self.assertEqual(h["teams"], {"blue": {"name": "T1", "full": "T1"},
                                      "red": {"name": "BLG", "full": "Bilibili Gaming"}})
        self.assertEqual(h["players"][0], {"side": "blue", "team": "T1", "role": "support", "name": "Keria",
                                           "champion": {"name": "Poppy", "ko": "뽀삐", "skills": {"Q": "Poppy-Q"}}})
        self.assertEqual(h["bans"]["red"], [{"name": "Annie", "ko": "애니"}])
        s = h["series"]
        self.assertEqual(s["score_before"], {"BLG": 1, "T1": 0})
        self.assertEqual(s["previous"][0]["winner"], "BLG")
        self.assertEqual(s["previous"][0]["bans"], {"blue": [{"name": "Jax", "ko": "잭스"}], "red": []})
        # 피어리스: 1세트에 T1 이 고른 진은 2세트에 못 고른다. 밴(잭스)은 넘어가지 않는다
        self.assertEqual(s["fearless_unavailable"], [{"name": "Jhin", "ko": "진", "set": 1, "team": "T1"}])
        empty = MatchGame.objects.create(match=match, number=3)  # 선수가 없는 세트(op.gg 세트 정보 없음)
        self.assertEqual(build_header(empty), {})

    def test_pick_version(self):
        versions = ["16.23.1", "16.22.1", "16.21.2"]
        self.assertEqual(ddragon.pick_version(versions, "16.22.1"), "16.22.1")
        self.assertEqual(ddragon.pick_version(versions, "16.21.1"), "16.21.2")  # 같은 패치의 다른 버전
        self.assertEqual(ddragon.pick_version(versions, ""), "16.23.1")  # 모르면 최신
