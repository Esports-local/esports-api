"""/episodes 응답 모양. 스펙 시트의 인자 이름·순서를 그대로 따른다."""

from rest_framework import serializers

from api.serializers import blank_to_none
from config import storage
from vod.models import Episode, LineReview, Verdict


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
        return blank_to_none(obj.still)

    def get_play_url(self, obj) -> str | None:
        return storage.public_url(obj.hls_key)  # hls/ 는 공개 읽기 (storage.py 참고)


# ---------------------------------------------------------------- 검수

class LineReviewSerializer(serializers.ModelSerializer):
    text = serializers.SerializerMethodField()

    class Meta:
        model = LineReview
        fields = ["scene_id", "index", "verdict", "text", "updated_at"]

    def get_text(self, obj) -> str | None:
        return blank_to_none(obj.text)


class LineReviewListSerializer(serializers.Serializer):
    episode_id = serializers.IntegerField()
    items = LineReviewSerializer(many=True)


class LineReviewRequestSerializer(serializers.Serializer):
    scene_id = serializers.IntegerField(min_value=1, help_text="장면 id (analysis scenes[].id)")
    index = serializers.IntegerField(min_value=0, help_text="장면 안 대사 순서 (0부터)")
    verdict = serializers.ChoiceField(
        choices=[*Verdict.values, "clear"], help_text="ok | wrong | fixed | clear(판정 지우기)",
        error_messages={"invalid_choice": "verdict 는 ok, wrong, fixed, clear 중 하나여야 합니다"},
    )
    text = serializers.CharField(required=False, allow_blank=True, allow_null=True,
                                 help_text="고친 대사. fixed 일 때 필수이고 원문과 달라야 한다")


class LineReviewSavedSerializer(serializers.Serializer):
    review = LineReviewSerializer(allow_null=True)
