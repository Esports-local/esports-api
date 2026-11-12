"""에러 응답 형식 {"error": "메시지"} (api/exceptions.py)."""

from django.test import SimpleTestCase

from api.exceptions import first_message


class FirstMessageTests(SimpleTestCase):
    def test_empty_detail_does_not_crash(self):
        self.assertEqual(first_message({}), "잘못된 요청입니다")
        self.assertEqual(first_message([]), "잘못된 요청입니다")
        self.assertEqual(first_message({"x": {}}), "x: 잘못된 요청입니다")

    def test_field_prefix(self):
        self.assertEqual(first_message({"name": ["필수 항목입니다."]}), "name: 필수 항목입니다.")
        self.assertEqual(first_message({"target": ["target 이 필요합니다"]}), "target 이 필요합니다")
        self.assertEqual(first_message({"detail": "찾을 수 없습니다"}), "찾을 수 없습니다")
