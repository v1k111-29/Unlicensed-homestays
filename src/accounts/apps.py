from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Django app config for accounts. Django calls `ready()` once at startup."""

    name = "accounts"

    def ready(self) -> None:
        """Import the signal handlers so their receivers are connected."""
        from accounts import signals  # noqa: F401  (connects the audit receivers)
