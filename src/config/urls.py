"""URL routes. Auth in M6; officer pages in M7/M8; tourist pages in M9."""

from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
]
