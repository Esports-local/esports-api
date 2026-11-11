from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

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
    # 문서
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
]
