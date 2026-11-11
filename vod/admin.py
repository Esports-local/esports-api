from django.contrib import admin

from vod.models import Character, Episode, LineReview, Prediction, Series


class EpisodeInline(admin.TabularInline):
    model = Episode
    fields = ["number", "title", "air_date", "analyze_status", "hls_key"]
    extra = 0


class CharacterInline(admin.TabularInline):
    model = Character
    fields = ["order", "name", "actor", "aliases"]
    extra = 0


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "tmdb_id", "episode_count", "first_air_date"]
    inlines = [EpisodeInline, CharacterInline]


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ["id", "series", "number", "title", "analyze_status"]
    list_filter = ["series", "analyze_status"]


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ["id", "series", "name", "actor"]
    list_filter = ["series"]


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ["id", "series", "target", "status", "updated_at"]


@admin.register(LineReview)
class LineReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "episode", "scene_id", "index", "verdict", "updated_at"]
    list_filter = ["verdict", "episode__series"]
