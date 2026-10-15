"""URL routes for sign-in, sign-out and the signed-in landing page.

Included from the project URL conf in `config.urls`.
"""

from django.urls import path

from accounts import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
]
