"""테스트 공통: 데모 데이터(seed_demo)를 한 번 만들고 모든 테스트가 같이 쓴다."""

import io

from django.core.management import call_command
from django.test import TestCase, override_settings

from vod.models import Series


@override_settings(PREDICT_BACKEND="mock")
class DemoDataTestCase(TestCase):
    series: Series

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.series = Series.objects.get(tmdb_id=999999)
