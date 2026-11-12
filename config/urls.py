from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from api import views as common
from api.games import views as games

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", common.health),
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
