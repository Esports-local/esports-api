"""응답 모양. 스펙 시트의 인자 이름·순서를 그대로 따른다."""

from rest_framework import serializers

from vod import storage
from vod.models import Character, Episode, JobStatus, Prediction, Series


def _blank_to_none(value):
    return value or None


class SeriesListSerializer(serializers.ModelSerializer):
    poster = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = ["id", "title", "poster", "episode_count", "first_air_date"]

    def get_poster(self, obj) -> str | None:
        return _blank_to_none(obj.poster)


class EpisodeBriefSerializer(serializers.ModelSerializer):
    has_video = serializers.BooleanField(read_only=True)

    class Meta:
        model = Episode
        fields = ["id", "number", "title", "air_date", "has_video", "analyze_status"]


class CharacterSerializer(serializers.ModelSerializer):
    photo = serializers.SerializerMethodField()
    aliases = serializers.ListField(child=serializers.CharField())

    class Meta:
        model = Character
        fields = ["id", "name", "actor", "photo", "aliases"]

    def get_photo(self, obj) -> str | None:
        return _blank_to_none(obj.photo)


class CrewSerializer(serializers.Serializer):
    name = serializers.CharField()
    job = serializers.CharField()


class SeriesDetailSerializer(SeriesListSerializer):
    genres = serializers.ListField(child=serializers.CharField())
    crew = CrewSerializer(many=True)
    episodes = EpisodeBriefSerializer(many=True, read_only=True)
    characters = CharacterSerializer(many=True, read_only=True)

    class Meta(SeriesListSerializer.Meta):
        fields = SeriesListSerializer.Meta.fields + [
            "synopsis", "genres", "crew", "tmdb_id", "episodes", "characters",
        ]


class EpisodeDetailSerializer(serializers.ModelSerializer):
    still = serializers.SerializerMethodField()
    play_url = serializers.SerializerMethodField()

    class Meta:
        model = Episode
        fields = [
            "id", "series_id", "number", "title", "synopsis", "air_date",
            "still", "duration", "play_url", "analyze_status",
        ]

    def get_still(self, obj) -> str | None:
        return _blank_to_none(obj.still)

    def get_play_url(self, obj) -> str | None:
        return storage.public_url(obj.hls_key)  # hls/ 는 공개 읽기 (storage.py 참고)


# ---------------------------------------------------------------- 예측

class PredictRequestSerializer(serializers.Serializer):
    """POST 본문과 GET 쿼리에 같이 쓴다 (검증 규칙을 한 곳에)."""

    target = serializers.IntegerField(
        min_value=2, help_text="예측할 회차 번호 (2 이상). 11이면 1~10화를 사용",
        error_messages={
            "required": "target 이 필요합니다",
            "null": "target 이 필요합니다",
            "invalid": "target 은 정수여야 합니다",
            "min_value": "target 은 2 이상이어야 합니다",
        },
    )


class PredictAcceptedSerializer(serializers.Serializer):
    target = serializers.IntegerField()
    status = serializers.ChoiceField(choices=JobStatus.choices)


class SceneRefSerializer(serializers.Serializer):
    episode_id = serializers.IntegerField()
    scene_id = serializers.IntegerField()
    start = serializers.FloatField(help_text="장면 시작 시각(초)")
    end = serializers.FloatField(help_text="장면 끝 시각(초)")
    note = serializers.CharField()


class PredictionItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    text = serializers.CharField()
    category = serializers.ChoiceField(
        choices=["action", "discovery", "conflict", "relationship", "twist", "resolution"])
    characters = serializers.ListField(child=serializers.IntegerField())
    confidence = serializers.FloatField(min_value=0, max_value=1)
    evidence = SceneRefSerializer(many=True)
    counter_evidence = SceneRefSerializer(many=True)


class PredictionSerializer(serializers.ModelSerializer):
    used_episodes = serializers.ListField(child=serializers.IntegerField())
    error = serializers.SerializerMethodField()
    items = PredictionItemSerializer(many=True)

    class Meta:
        model = Prediction
        fields = ["series_id", "target", "used_episodes", "status", "error", "items"]

    def get_error(self, obj) -> str | None:
        return _blank_to_none(obj.error)


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()
