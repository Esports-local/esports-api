from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from api import views as common
from api.episodes import views as episodes
from api.games import views as games
from api.series import views as series

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", common.health),
    # series (드라마 작품 + 예측)
    path("series", series.series_list),
    path("series/<int:pk>", series.series_detail),
    path("series/<int:pk>/predict", series.series_predict),
    # episodes (드라마 회차 + 대사 검수)
    path("episodes/<int:pk>", episodes.episode_detail),
    path("episodes/<int:pk>/analysis", episodes.episode_analysis),
    path("episodes/<int:pk>/reviews", episodes.episode_reviews),
    # games (LoL 세트 영상)
    path("games", games.game_list),
    path("games/<int:pk>", games.game_detail),
    path("games/<int:pk>/screen", games.game_screen),
    path("games/<int:pk>/lines", games.game_lines),
    path("games/<int:pk>/analysis", games.game_analysis),
    path("games/<int:pk>/analyze", games.game_analyze),
    path("games/<int:pk>/cancel", games.game_cancel),
    path("games/<int:pk>/estimate", games.game_estimate),
    path("sources", games.source_list),
    # 문서
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
]
