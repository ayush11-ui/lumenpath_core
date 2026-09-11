"""URL routes for the `routing` app."""

from django.urls import path
from . import views

urlpatterns = [
    # Single-page UI
    path("", views.index, name="index"),
    # JSON APIs
    path("api/routes/", views.routes_api, name="routes_api"),
    path("api/segments/", views.segments_api, name="segments_api"),
    path("api/safe-zones/", views.safe_zones_api, name="safe_zones_api"),
    path("api/incidents/", views.incidents_api, name="incidents_api"),
    path("api/incidents/report/", views.report_incident, name="report_incident"),
    path("api/sessions/", views.create_session, name="create_session"),
    path("api/sessions/<uuid:token>/", views.get_session, name="get_session"),
]