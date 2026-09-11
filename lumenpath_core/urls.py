"""Root URL configuration for the LumenPath project."""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    # All LumenPath routes (UI + APIs) live in the `routing` app.
    path("", include("routing.urls")),
]