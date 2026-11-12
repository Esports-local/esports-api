from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from matches import views as games
from vod import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", views.health),
    # series
    path("series", views.series_list),
    path("series/<int:pk>", views.series_detail),
    path("series/<int:pk>/predict", views.series_predict),
    # episodes
    path("episodes/<int:pk>", views.episode_detail),
    path("episodes/<int:pk>/analysis", views.episode_analysis),
    path("episodes/<int:pk>/reviews", views.episode_reviews),
    # games (LoL 세트 영상)
    path("games", games.game_list),
    path("games/<int:pk>", games.game_detail),
    path("games/<int:pk>/screen", games.game_screen),
    path("games/<int:pk>/lines", games.game_lines),
    path("games/<int:pk>/analysis", games.game_analysis),
    # 문서
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
]
