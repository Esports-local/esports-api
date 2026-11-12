from django.contrib import admin

from matches.models import GamePlayer, LineReview, Match, MatchGame, Team


class MatchGameInline(admin.TabularInline):
    model = MatchGame
    extra = 0


class GamePlayerInline(admin.TabularInline):
    model = GamePlayer
    extra = 0


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ["opgg_id", "name", "league", "stage", "begin_at", "home_score", "away_score", "winner"]
    inlines = [MatchGameInline]


@admin.register(MatchGame)
class MatchGameAdmin(admin.ModelAdmin):
    list_display = ["match", "number", "opgg_game_id", "blue_team", "red_team", "winner"]
    inlines = [GamePlayerInline]


admin.site.register(Team)
admin.site.register(LineReview)
