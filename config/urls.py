from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from api import views as common
from api.games import views as games
from api.shorts import views as shorts
from api.skills import views as skills

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", common.health),
    # games (LoL 세트 영상)
    path("games", games.game_list),
    path("games/<int:pk>", games.game_detail),
    path("games/<int:pk>/screen", games.game_screen),
    path("games/<int:pk>/lines", games.game_lines),
    path("games/<int:pk>/lines/<int:line_id>/review", games.game_line_review),
    path("games/<int:pk>/analysis", games.game_analysis),
    path("games/<int:pk>/analyze", games.game_analyze),
    path("games/<int:pk>/cancel", games.game_cancel),
    path("sources", games.source_list),
    # 경기 이벤트·숏폼 (14~17번)
    path("games/<int:pk>/events", shorts.game_events),
    path("games/<int:pk>/shorts", shorts.game_shorts),
    path("shorts/<int:pk>", shorts.short_detail),
    # skills (Claude Code 스킬 사용 기록·선택 평가)
    path("skills", skills.skill_list),
    path("skills/usage", skills.skill_usage),
    path("skills/evals", skills.skill_evals),
    path("skills/cases", skills.eval_cases),
    path("skills/cases/sync", skills.eval_cases_sync),
    path("skills/cases/<str:case_id>", skills.eval_case),
    path("skills/evals/jobs", skills.eval_jobs),
    path("skills/improves", skills.improve_tries),
    path("skills/fixes", skills.eval_fixes),
    path("skills/evals/runner", skills.eval_runner),
    path("skills/evals/jobs/claim", skills.eval_job_claim),
    path("skills/evals/jobs/<int:pk>/progress", skills.eval_job_progress),
    path("skills/evals/jobs/<int:pk>/cancel", skills.eval_job_cancel),
    # 문서
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
]
